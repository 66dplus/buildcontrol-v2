# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role

You are a Python engineer maintaining BuildControl MVP — a construction project control system
built on Bitrix24 REST API + FastAPI. You write working code, test every step, and confirm
results before moving on. When unsure about an API method, use the `bitrix24-docs` MCP tool.

---

## MCP Tools Available

### `bitrix24-docs` — Official Bitrix24 API documentation (no auth required)
Use this to look up any REST API method, its parameters, return values, examples.
Use this MCP tool instead of guessing. It always returns current, accurate docs.

---

## Project Context

BuildControl tracks construction project plan vs actual with anti-fraud controls:
- Director uploads Excel plan → creates Bitrix24 project + 5 universal lists + CRM tasks
- Foreman fills daily report form (embedded Bitrix24 iframe widget) → fact data flows to lists
- Cascade logic recomputes Бюджет факт per task, then per phase, after each report
- Smart routing: 5% deviation → auto-approve, 15% → manager, >15% → director
- Target user: construction director (5–15 active sites, 50–300M RUB/year)

---

## Architecture

### Data Flow

```
Excel v3 file
    └─► scripts/import_excel.py (ExcelImporter)
            ├─► workgroups.create_project() → Bitrix24 workgroup
            ├─► lists.create_list() × 5 sheets → Universal Lists (NAME + PROPERTY_XX fields)
            └─► tasks.create_task() × N rows from "2. Этапы и задачи" → Bitrix CRM tasks

Buyer (закупщик) submits purchase
    └─► POST /api/buyer-report
            ├─► Объём куплено += qty_bought
            ├─► Остаток на складе += qty_bought
            └─► Цена ед. факт = running weighted average (prev_cost + cost_bought) / total_qty

Foreman in Bitrix24 iframe
    └─► app/bitrix_app.py (GET /bitrix/widget)  ← HTML form with JS
            ├─► GET /api/projects → list projects
            ├─► GET /api/projects/{id}/tasks → task dropdown (includes bitrix_task_id)
            ├─► GET /api/projects/{id}/stages → kanban stage dropdown (parallel with tasks)
            ├─► GET /api/projects/{id}/materials|labor|equipment?etap=X&zadacha=Y → populate rows
            └─► POST /api/report → save fact values + update stage/comment + trigger cascade

POST /api/report
    └─► app/webhook_handler.py (api_report)
            ├─► "3. Материалы": Объём израсходовано += qty, Остаток -= qty, Стоим. факт += qty × price
            ├─► "4. Трудозатраты": Ч-часов факт += hours, ФОТ факт = total_hours × ставка
            ├─► "5. Техника": Часов факт += hours, Итого факт = кол-во × цена × total_hours
            ├─► utils/cascade.py
            │       ├─► cascade_update_task()  → sums Стоим. факт + ФОТ факт + Итого факт → "Бюджет факт" in "2. Этапы и задачи"
            │       └─► cascade_update_budget() → sums per-Этап → Материалы факт, ФОТ факт, Техника факт, Итого факт in "1. Бюджет"
            └─► _update_task_progress() (per task, if stage_id or comment provided)
                    ├─► Resolves CRM task ID from "Bitrix Task ID" list property (or name-search fallback)
                    ├─► task.stages.get → get all stages; derive SYSTEM_TYPE by position if Bitrix returns null
                    │       (index 0 → "NEW", last index → "FINISH", middle → "PROGRESS")
                    ├─► task.stages.movetask → move kanban stage
                    ├─► tasks.task.start  (if SYSTEM_TYPE not NEW or FINISH)
                    ├─► tasks.task.complete (if SYSTEM_TYPE == FINISH)
                    ├─► task.commentitem.add → post comment to task chat
                    └─► lists.element.update → write Дата нач. факт (first non-NEW move) +
                                               Дата ок. факт (FINISH stage, written once) +
                                               % выполнения факт
```

### Excel Template v3 Sheet Structure

| Sheet | List keyword | NAME column | Key columns |
|-------|-------------|-------------|-------------|
| 1. Бюджет | бюджет | headers[0] (Этап) | Материалы факт, ₽ · ФОТ факт, ₽ · Техника факт, ₽ · Итого факт, ₽ |
| 2. Этапы и задачи | задач | Задача | Этап, Дата нач. план, Дата ок. план, Бюджет факт, ₽, **Дата нач. факт** (S:Date), **Готовн. факт, %** (N), **Bitrix Task ID** (N) |
| 3. Материалы | материал | Наименование | Этап, Задача, Цена ед. план, ₽, Объём план, Стоим. план, ₽, Цена ед. факт, ₽, Объём куплено, Объём израсходовано, Остаток на складе, Стоим. факт, ₽ |
| 4. Трудозатраты | трудозатрат | Специальность | Этап, Задача, Ставка, ₽/час, Ч-часов план, ФОТ план, ₽, Ч-часов факт, ФОТ факт, ₽ |
| 5. Техника | техник | Техника | Этап, Задача, Цена, ₽/час, Часов план, Итого план, ₽, Часов факт, Итого факт, ₽ |

`_NAME_COLUMN_KEYWORDS` in `scripts/import_excel.py` controls which column becomes the Bitrix element NAME.

### Bitrix24 Universal Lists — field storage

- Every column in Excel becomes a `PROPERTY_XX` field (type S/N/S:Date)
- Field ID mapping is resolved per-list via `lists.resolve_field_map()` which returns `{header → property_id}`
- Filtering by Этап/Задача uses `lists.find_elements_by_properties()` — partial case-insensitive keyword match on the header name
- `_get_list_context()` in `utils/cascade.py` is the canonical helper: takes a keyword, returns `(list_id, iblock_code, field_map, elements)`
- **Keyword pitfall**: sheet "2. Этапы и задачи" has BOTH `"Готовн. план, %"` and `"Готовн. факт, %"`. Always use the specific keyword `"готовн. факт"` (not `"готовн"`) when resolving the completion-% property, or you'll write to the plan column instead.

### Stage SYSTEM_TYPE — position-based fallback

`task.stages.get` returns `SYSTEM_TYPE = null` for custom/manually-created stages (the common case).
Both `api_stages()` and `_update_task_progress()` fall back to position:

| Position | Assigned SYSTEM_TYPE | Russian title |
|----------|---------------------|---------------|
| index 0 (lowest SORT) | `NEW` | Новая |
| last index (highest SORT) | `FINISH` | Завершена |
| everything else | `PROGRESS` | original title from Bitrix |

This drives Russian display names, task lifecycle calls, and `Дата ок. факт` / `Дата нач. факт` writes.

### Rate Limiting

Bitrix24 allows 2 req/sec per webhook. `bitrix/client.py` enforces:
- 0.5s minimum interval between calls
- Auto-retry up to 5× with exponential backoff on `QUERY_LIMIT_EXCEEDED`
- **Concurrent load**: 5 retries are sufficient for sequential single-user use. Under ≥10 concurrent report POSTs the retry budget can exhaust → HTTP 500. Not a concern for the normal one-foreman-one-form flow; if multi-site concurrency grows, raise `MAX_RETRIES` or add a server-side request queue.

---

## Environment & Stack

- Python 3.13 (local) / 3.12 on VPS — always use venv
- Key env vars: `BITRIX24_WEBHOOK_URL`, `BITRIX24_DOMAIN`, `VPS_URL`, `VPS_PASSWORD`
- VPS: `162.120.19.127`, app at `/opt/buildcontrol/`, venv at `/opt/buildcontrol/venv/`
- Service: `systemd` unit `buildcontrol` (uvicorn on port 8000)
- Public HTTPS: Cloudflare Tunnel (`cloudflared`) → temporary `*.trycloudflare.com` URL

---

## Commands

```bash
# Local dev
pip install -r requirements.txt
python -m pytest tests/ -v
python scripts/import_excel.py template_data/plan_fact_v3.xlsx

# Deploy to VPS (rsync + restart — BOTH steps required)
cd "/Users/dmitrijrybkin/Documents/Claude Code/BuildControl_v2"
SSHPASS='<password>' sshpass -e /usr/bin/rsync -avz \
  --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.git' --exclude='venv' --exclude='template_data' \
  -e "ssh -o StrictHostKeyChecking=no" \
  ./ root@162.120.19.127:/opt/buildcontrol/
ssh root@162.120.19.127 "systemctl restart buildcontrol && systemctl status buildcontrol --no-pager"

# VPS diagnostics
ssh root@162.120.19.127 "journalctl -u buildcontrol -n 100 --no-pager"
curl http://162.120.19.127:8000/health
curl "http://162.120.19.127:8000/api/projects/{ID}/tasks"
curl "http://162.120.19.127:8000/api/projects/{ID}/materials?etap=X&zadacha=Y"
```

---

## Code Style

- Type hints required on all functions
- Use httpx (not requests) for async-friendly HTTP calls
- All Bitrix24 calls go through `bitrix/client.py` — never call the API directly
- Log to stdout with timestamps; no silent failures

---

## Critical Rules

- NEVER commit `.env`
- NEVER guess Bitrix24 API params — use `bitrix24-docs` MCP tool first
- **After every code deploy to VPS, run `systemctl restart buildcontrol`** — uvicorn does NOT hot-reload Python modules; skipping this means old code stays in memory silently
- When adding a new feature, update `.env.example` if new env vars are needed

---

## Documentation Rules

After **every** code change, update both docs in the same session before reporting the task done:

**README.md** — developer-facing: import pipeline, foreman/buyer report flow, cascade logic,
project structure, API endpoint table, known limitations.

**prod_info.md** — ops-oriented: endpoint table, deploy procedure, tunnel setup, troubleshooting.

Skip only for purely internal refactors that change no behavior visible to developers or operators.
