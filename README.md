# BuildControl

Construction project management MVP built on top of Bitrix24's REST API. A director uploads an Excel plan → the system creates a Bitrix24 project with structured Universal Lists and CRM tasks → foremen submit daily reports via an embedded iframe widget → fact data rolls up through a cascade to plan/actual comparisons at the task and phase level.

---

## How It Works

### 1. Import Pipeline

```
Excel v3 or v4 (.xlsx)
  └─► POST /upload (or CLI: python scripts/import_excel.py <file>)
        └─► ExcelImporter (scripts/import_excel.py)
              ├─ create Bitrix24 workgroup (project)
              ├─ create Universal Lists (one per sheet)
              │     ├─ 1. Бюджет          — phase-level budget (plan + fact)
              │     ├─ 2. Этапы и задачи  — task list with dates + progress %
              │     ├─ 3. Материалы        — materials per task
              │     ├─ 4. Трудозатраты     — labor per task
              │     ├─ 5. Техника          — equipment per task
              │     └─ 6. Подзадачи        — subtasks per task (v4 only)
              └─ create Bitrix CRM tasks from "2. Этапы и задачи" sheet
                    (each task gets UF_ETAP custom field = phase name)
              [v4 only] "6. Подзадачи" rows are stored as Universal List elements only
                    (no Bitrix child tasks created — keeps native task list/kanban uncluttered)
```

**Excel versions:**
- **v3** — 5 sheets. Foreman manually selects a Kanban stage per task.
- **v4** — 6 sheets. Adds "6. Подзадачи": subtasks with names, planned start/end dates, and status. Foreman marks individual subtask completion instead of selecting a stage. Template: [template_data/plan_fact_v4.xlsx](template_data/plan_fact_v4.xlsx)

Every Excel column becomes a `PROPERTY_XX` field in the Universal List. The element `NAME` field is set to the domain column (e.g. "Задача", "Наименование", "Специальность", "Техника", "Название"), not the first column. `_NAME_COLUMN_KEYWORDS` in [scripts/import_excel.py](scripts/import_excel.py) controls this mapping.

### 2. Procurement Approval (purchase request)

A buyer submits `POST /api/purchase-request` (multipart/form-data) with:

- `project_id`
- `items_json` — JSON array of `{material_name, qty, price, unit?, total?, price_plan?}` (the buyer form fills `price_plan` from the materials API so the server can enforce comment-when-overpriced)
- `proposal` — **REQUIRED** counterparty document (PDF only, ≤ `MAX_PROPOSAL_FILE_MB`)
- `buyer_comment` — **REQUIRED when** any item's `price > price_plan` (justification of the overspend)

The buyer's name, Этап, and Задача are not collected from the form — author is hardcoded to `"Закупщик"` (user_id = 1) until `BX24.callMethod('user.current')` is wired in. The handler does **not** mutate "3. Материалы". Instead it:

1. Uploads the proposal to the workgroup's Bitrix24 Disk in folder `Заявки на закупку`.
2. Creates a row in the project's "Заявки на закупку" universal list (status `Ожидает`), creating the list lazily on first use via `lists.get_or_create_purchase_requests_list`. Buyer's justification is persisted to `f_pr_comment`.
3. Creates a Bitrix24 audit task assigned to `PURCHASE_APPROVER_USER_ID` with `UF_TASK_WEBDAV_FILES` linking the proposal and a description that includes the buyer's comment + the approval-page URL (kept for backwards-compat with Telegram).
4. Sends a Telegram message with a graded price-deviation banner (✅ ok / 🟡 ≤ 2% / 🟠 ≤ 5% ОБРАТИТЕ ВНИМАНИЕ / 🔴 ≤ 10% ВНИМАНИЕ / 🚨 > 10% КРИТИЧЕСКОЕ ПРЕВЫШЕНИЕ ПЛАНА) — see `format_price_deviation()` in `app/purchase_requests.py`. The message includes overspend in rubles. Inline keyboard:
   - `✅ Подтвердить` / `❌ Отклонить` — `callback_data=pr:<action>:<request_id>`
   - `📝 Открыть форму` — URL deep-link to the external approval page
   - `💬 Написать` — puts the chat in comment mode; the next message becomes a request comment

The approver decides in three places:

- **Bitrix widget tab "Согласование"** (preferred) — lists every pending request across all projects; clicking one renders the same items table + graded severity banner + buyer comment + decision buttons inside the iframe. Backed by `GET /api/purchase-requests/pending`, `GET /api/purchase-requests/{id}`, `POST /api/purchase-requests/{id}/decide`. Actor name hardcoded `"Согласующий"`.
- **External approval page** at `GET /approval/{id}?token=<HMAC>` (HMAC signed with `APPROVAL_LINK_SECRET`) — kept for Telegram link backwards-compat. The actor-name input and history card were removed; actor is hardcoded `"Согласующий"`. Buttons POST to `/approval/{id}/decide`.
- **Telegram** — `POST /tg/webhook` (header `X-Telegram-Bot-Api-Secret-Token` checked against `TELEGRAM_WEBHOOK_SECRET`) handles `callback_query` events and the comment follow-up message.

All three routes call `purchase_requests.resolve_request`, which is idempotent — it reads the row's current status and ignores duplicate Approve/Reject if the request is no longer pending. On Approve, `_apply_buyer_purchase` runs (extracted from the legacy buyer-report logic):

- `Объём куплено` += `qty`
- `Остаток на складе` += `qty`
- `Цена ед. факт, ₽` = running weighted average

…and the existing `cascade_update_task` + `cascade_update_budget` fire for affected (Этап, Задача) pairs. On Reject the list row is just marked `Отклонено`. **On both Approve and Reject** the audit task is closed via `tasks.task.complete`. Comments append to the row's history JSON, are mirrored to the Bitrix task chat, and trigger a Telegram ack.

The buyer success screen no longer shows an approval link — it just confirms `Заявка №N отправлена на согласование.` The legacy `POST /api/buyer-report` endpoint still returns HTTP 410.

### 3. Foreman Report Form

A Bitrix24 local app embeds an iframe widget at `/bitrix/widget`. The JS:

1. Loads active projects via `GET /api/projects`
2. On project select, loads tasks via `GET /api/projects/{id}/tasks` (root tasks only, no subtasks in dropdown)
3. On task select, loads resources + subtasks in one request filtered by `?etap=X&zadacha=Y`:
   - `GET /api/projects/{id}/task-context` (returns `materials`, `labor`, `equipment`, `subtasks`)
4. Foreman manually adds rows for materials/labor/equipment and enters fact quantities; for v4 projects marks subtasks as "В работе" / "Готово", for v3 tasks (without subtasks) selects a Kanban stage; optionally writes a comment
5. `POST /api/report` saves resource quantities, then:
   - **v4 (subtasks present):** updates each subtask's status + dates in the Universal List, recomputes `Готовн. факт, %` as `completed / total × 100`, auto-advances parent Kanban stage, posts auto-generated status lines ("▶️ Подзадача начата: …" / "✅ Подзадача выполнена: …") + foreman's manual comment to parent task chat
   - **v3 (no subtasks):** moves parent task to the selected Kanban stage, calls `tasks.task.start` / `tasks.task.complete` based on stage position, posts comment

### 4. Cascade Update

After each foreman or buyer report, `utils/cascade.py` runs two passes:

- `cascade_update_task()` — sums `Стоим. факт` (materials) + `ФОТ факт` (labor) + `Итого факт` (equipment) for the (Этап, Задача) pair → writes total to `Бюджет факт, ₽` in "2. Этапы и задачи"
- `cascade_update_budget()` — sums all rows for the Этап across all three resource lists → writes `Материалы факт, ₽`, `ФОТ факт, ₽`, `Техника факт, ₽`, `Итого факт, ₽` to the phase row in "1. Бюджет"

Additionally, `app/webhook_handler.py` handles task progress in two modes:

**v3 — `_update_task_progress()`** (Kanban stage selection):
- Fetches kanban stages and derives `SYSTEM_TYPE` by position when Bitrix24 returns `null` (index 0 → `NEW`, last → `FINISH`, middle → `PROGRESS`)
- Moves the Bitrix24 CRM task to the selected kanban stage (`task.stages.movetask`)
- Calls `tasks.task.start` (non-NEW/FINISH stages) or `tasks.task.complete` (FINISH stage) to sync task status
- Posts a comment to the task chat (`task.commentitem.add`)
- Writes `Дата нач. факт` (first non-NEW move), `Дата ок. факт` (FINISH, once), and `Готовн. факт, %` (stage index / max stages × 100) to the "2. Этапы и задачи" element

**v4 — `_update_subtask_progress()`** (subtask completion):
- Updates each subtask's `Статус`, `Дата нач. факт`, `Дата ок. факт` in the "6. Подзадачи" Universal List
- Recomputes parent `Готовн. факт, %` = `completed / total × 100`
- Auto-advances parent Kanban: any subtask started → move parent to first progress stage + `tasks.task.start`; all done → move parent to finish stage + `tasks.task.complete`
- Posts a single comment to the parent Bitrix task combining auto-generated status lines ("▶️ Подзадача начата: …" / "✅ Подзадача выполнена: …") and the foreman's manual comment (if provided)
- Checks for overdue subtasks (`Дата ок. план < today`) and fires Telegram alerts

### 5. Director Telegram Agent

The director can ask natural-language questions in Russian about any project directly in Telegram.

```
Director → Telegram message
  → POST /tg/webhook
    → chat_id checked against TELEGRAM_DIRECTOR_CHAT_IDS allowlist
    → app/telegram_agent.py: OpenRouter (openai/gpt-4.1-mini) tool-use loop
        → tools call bitrix/project_analytics.py
            ├─ list_projects            — all active projects
            ├─ get_schedule_analysis    — tasks classified as done / overdue / in progress / not started
            ├─ get_budget_overview      — per-phase plan vs actual: Materials / Labor / Equipment
            ├─ get_resource_costs       — row-level detail for any (etap, zadacha)
            └─ get_upcoming_tasks       — tasks starting/ending in the next N days
    → formatted Russian answer → back to Telegram
```

**Example queries:**
- «Расскажи про объект Москва Березки» → schedule + budget overview
- «Что должны были закончить на этой неделе?» → overdue + in-progress tasks
- «Бюджет по этапу Фундамент» → phase-level breakdown
- «Какие расходы на топливо?» → resource costs filtered by keyword

**Adding write tools** (future): register a new entry in `TOOL_REGISTRY` in `app/telegram_agent.py` with a JSON schema dict and an async handler. The agent loop picks it up automatically.

---

## Project Structure

```
bitrix/
  client.py              # All Bitrix24 HTTP calls go here. Handles rate limiting
                         # (0.5s interval + retry on QUERY_LIMIT_EXCEEDED × 5)
  methods/
    lists.py             # Universal Lists CRUD + field resolution helpers
    tasks.py             # CRM task create + UF_ETAP custom field setup
    workgroups.py        # Project (sonet group) creation
  project_analytics.py   # Read-only analytics: schedule, budget, resources (used by Telegram agent)

scripts/
  import_excel.py        # ExcelImporter class — full import orchestrator (CLI-runnable)

utils/
  excel_parser.py        # Reads .xlsx, detects header rows, returns {sheet: [row_dicts]}
  cascade.py             # Plan vs actual cascade logic (task + budget level)

app/
  webhook_handler.py     # FastAPI app — all HTTP endpoints
  bitrix_app.py          # Bitrix24 iframe install/widget routes + HTML form
  telegram_agent.py      # Director AI agent: OpenRouter tool-use loop

config.py                # Settings from .env (BITRIX24_WEBHOOK_URL, BITRIX24_DOMAIN, VPS_URL)
template_data/           # Excel templates: plan_fact_v3.xlsx (5 sheets) and plan_fact_v4.xlsx (6 sheets + subtasks)
```

---

## Key Internals

### Field Resolution

Bitrix24 Universal Lists store data in dynamically-numbered `PROPERTY_XX` fields. After creating a list you don't know the IDs until you call `lists.getfields`. The flow:

```python
fields_resp = await lists.get_fields(client, list_id, iblock_code, group_id)
field_map = lists.resolve_field_map(fields_resp)  # → {"Наименование": 123, "Этап": 124, ...}
```

Filtering uses keyword matching on header names (case-insensitive, partial), not exact IDs:

```python
lists.find_elements_by_properties(elements, field_map, {"Этап": "3. Фундамент", "Задача": "Монолитный ростверк"})
```

`_get_list_context(client, project_id, keyword)` in `utils/cascade.py` is the reusable helper that does the full lookup: find list by name keyword → get fields → get elements.

### Rate Limiting

Bitrix24 enforces 2 req/sec per webhook. `BitrixClient.call()` enforces a 0.5s minimum interval between calls and retries up to 5× with exponential backoff (2s, 4s, 6s…) on `QUERY_LIMIT_EXCEEDED`. Without this, bulk imports of 20+ rows hit the limit and silently drop rows.

### Bitrix24 App Install

`POST /bitrix/install` is called by Bitrix24 when the local app is opened. It registers a `LEFT_MENU` widget pointing to `/bitrix/widget` and calls `BX24.installFinish()`. On subsequent opens, Bitrix24 calls the same endpoint again if `installFinish` wasn't called — it's idempotent.

---

## Setup

### Local

```bash
cp .env.example .env
# fill in BITRIX24_WEBHOOK_URL and BITRIX24_DOMAIN
pip install -r requirements.txt

# Run a test import
python scripts/import_excel.py template_data/plan_fact_v3.xlsx

# Start the API server locally
uvicorn app.webhook_handler:app --reload --port 8000
```

### Required `.env` keys

| Key | Description |
|-----|-------------|
| `BITRIX24_WEBHOOK_URL` | Full webhook URL including token |
| `BITRIX24_DOMAIN` | Portal domain (e.g. `mycompany.bitrix24.ru`) |
| `VPS_URL` | Public HTTPS URL of this server (Cloudflare tunnel URL) |
| `LOG_LEVEL` | `INFO` or `DEBUG` |

---

## VPS & Deploy

- **Server:** `162.120.19.127`, app at `/opt/buildcontrol/`, Python venv at `venv/`
- **Service:** `systemd` unit `buildcontrol` (uvicorn on port 8000, not exposed directly)
- **Public HTTPS:** Cloudflare Tunnel → temporary `*.trycloudflare.com` URL (changes on restart)

Deploy = rsync + **mandatory service restart** (uvicorn does not hot-reload Python modules):

```bash
cd "/Users/dmitrijrybkin/Documents/Claude Code/BuildControl_v2"

SSHPASS='<password>' sshpass -e /usr/bin/rsync -avz \
  --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.git' --exclude='venv' --exclude='template_data' \
  -e "ssh -o StrictHostKeyChecking=no" \
  ./ root@162.120.19.127:/opt/buildcontrol/

ssh root@162.120.19.127 "systemctl restart buildcontrol && systemctl status buildcontrol --no-pager"
```

See [prod_info.md](prod_info.md) for full ops details, Cloudflare tunnel setup, and troubleshooting.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/upload` | Upload `.xlsx` → create project + lists + tasks |
| GET | `/api/projects` | List active (non-archived) workgroups |
| GET | `/api/projects/{id}/tasks` | Root tasks from "2. Этапы и задачи" list (deduplicated; includes `bitrix_task_id`) |
| GET | `/api/projects/{id}/stages` | Kanban stages for a project (sorted by SORT) |
| GET | `/api/projects/{id}/task-context` | Combined task payload (`materials`, `labor`, `equipment`, `subtasks`) for `?etap=X&zadacha=Y` |
| GET | `/api/projects/{id}/materials` | Materials; accepts `?etap=X&zadacha=Y` |
| GET | `/api/projects/{id}/labor` | Labor; accepts `?etap=X&zadacha=Y` |
| GET | `/api/projects/{id}/equipment` | Equipment; accepts `?etap=X&zadacha=Y` |
| GET | `/api/projects/{id}/subtasks` | Subtasks for a task; requires `?etap=X&zadacha=Y`; returns `[]` for v3 projects |
| POST | `/api/buyer-report` | **Deprecated (410)** — pointer to `/api/purchase-request` |
| POST | `/api/purchase-request` | Submit a procurement approval request (multipart, REQUIRED `proposal` PDF file, REQUIRED `buyer_comment` if any item priced over plan) |
| GET | `/api/purchase-requests/pending` | List all pending requests across projects (used by widget Согласование tab) |
| GET | `/api/purchase-requests/{id}` | JSON detail for one request, with graded severity per item (widget) |
| POST | `/api/purchase-requests/{id}/decide` | Apply approve / reject / comment from the widget (no token, trusts Bitrix iframe session) |
| GET | `/approval/{id}` | External approval page (HMAC token in `?token=`) — kept for Telegram backwards-compat |
| GET | `/approval/{id}/state` | JSON snapshot of request status + history (used by page polling) |
| POST | `/approval/{id}/decide` | Apply approve / reject / comment from the external page |
| POST | `/tg/webhook` | Telegram bot webhook (callback_query + comment follow-up) |
| POST | `/api/report` | Save foreman report + trigger cascade + update task stage/comment |
| POST | `/bitrix/install` | Bitrix24 app install handler |
| GET | `/bitrix/widget` | Bitrix24 iframe widget (foreman form) |
| GET | `/bitrix/rebind` | Re-register LEFT_MENU widget after Cloudflare tunnel URL change (`?domain=&auth=`) |

---

## Known Limitations

- `RESPONSIBLE_ID` and `CREATED_BY` on created tasks are hardcoded to user `1` (MVP)
- Cloudflare Tunnel URL changes on every restart — update `VPS_URL` in `.env`, restart the service, then call `GET /bitrix/rebind?domain=YOUR_DOMAIN&auth=AUTH_TOKEN` to re-register the LEFT_MENU widget without reinstalling the app
- No authentication on API endpoints — they're protected only by the VPS not being publicly linked
- Negative quantities in foreman reports are accepted and cascade through (e.g. `Объём израсходовано` goes negative); no input validation at the API layer
- `task.commentitem.getlist` returns `[]` via REST even after a successful `task.commentitem.add` — a known Bitrix24 REST API quirk; comments ARE posted (confirmed by the comment ID returned from `add`)
- Under ≥10 concurrent `/api/report` calls the Bitrix24 rate-limit retry budget (5×) can exhaust, causing HTTP 500. The normal single-foreman form usage is unaffected; multi-site concurrency would require raising `MAX_RETRIES` or queuing

## Bitrix UI Root-Only Filter (safe mode)

To hide subtasks from the main Tasks list/Kanban in standard Bitrix UI:

1. Open **Tasks and Projects** → project tasks list (or project Kanban)
2. Open **Filter + Search**
3. Add field **Parent task** and set it to **is empty**
4. Save filter (e.g. `Root tasks only`)
5. In filter settings, enable **Apply for all users** (public/shared filter)

Result: main list/Kanban shows only root tasks; subtasks remain visible inside parent task cards.
