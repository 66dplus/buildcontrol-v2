# BuildControl

> **Work in Progress** — actively developed portfolio project. Core import pipeline and foreman reporting are functional; some features are still being refined.

Construction project management MVP built on top of Bitrix24's REST API. A director uploads an Excel plan → the system creates a Bitrix24 project with structured Universal Lists and CRM tasks → foremen submit daily reports via an embedded iframe widget → fact data rolls up through a cascade to plan/actual comparisons at the task and phase level.

→ [docs/roadmap.md](docs/roadmap.md) — 6–8 week plan to evolve this into a real AI-first product (custom UI, agent write-actions, voice, NL onboarding)
→ [docs/effort-estimate.md](docs/effort-estimate.md) — per-task hour estimates assuming Claude + subagents

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

Two entry points — the legacy Bitrix24 iframe widget and the new React SPA foreman page (`/foreman-report`).

**React SPA (preferred for standalone host):** Project → Phase → Task cascade selectors load from SQLite. After selecting a task, materials / labor / equipment rows load in parallel. Foreman enters fact quantities and optionally writes a comment, then submits `POST /api/report`.

**Legacy Bitrix24 iframe widget** at `/bitrix/widget`. The JS:

1. Loads active projects via `GET /api/projects`
2. On project select, loads tasks via `GET /api/projects/{id}/tasks` (root tasks only, no subtasks in dropdown)
3. On task select, loads resources + subtasks in one request filtered by `?etap=X&zadacha=Y`:
   - `GET /api/projects/{id}/task-context` (returns `materials`, `labor`, `equipment`, `subtasks`)
4. Foreman manually adds rows for materials/labor/equipment and enters fact quantities; for v4 projects marks subtasks as "В работе" / "Готово", for v3 tasks (without subtasks) selects a Kanban stage; optionally writes a comment
5. `POST /api/report` saves resource quantities, then:
   - **v4 (subtasks present):** updates each subtask's status + dates in the Universal List, recomputes `Готовн. факт, %` as `completed / total × 100`, auto-advances parent Kanban stage, posts auto-generated status lines ("▶️ Подзадача начата: …" / "✅ Подзадача выполнена: …") + foreman's manual comment to parent task chat
   - **v3 (no subtasks):** moves parent task to the selected Kanban stage, calls `tasks.task.start` / `tasks.task.complete` based on stage position, posts comment

### 4. Cascade Update + Budget Snapshot

After each foreman or buyer report, `utils/cascade.py` runs two passes:

- `cascade_update_task()` — sums `Стоим. факт` (materials) + `ФОТ факт` (labor) + `Итого факт` (equipment) for the (Этап, Задача) pair → writes total to `Бюджет факт, ₽` in "2. Этапы и задачи"
- `cascade_update_budget()` — sums all rows for the Этап across all three resource lists → writes `Материалы факт, ₽`, `ФОТ факт, ₽`, `Техника факт, ₽`, `Итого факт, ₽` to the phase row in "1. Бюджет"

After cascade completes, `app/routes/reports.py` also upserts a row in `budget_snapshots` (one row per project per day), recording the day's running `mat_actual`, `lab_actual`, `eq_actual`, `total_actual` totals. These snapshots power the **Plan vs Fact over Time** chart on the React SPA dashboard and project detail pages.

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

### 5. React SPA (Director UI)

A Vite + React + TypeScript single-page app served from `frontend/`. It talks only to the FastAPI backend — no direct Bitrix24 calls.

| Page | Route | Key content |
|------|-------|-------------|
| Dashboard | `/` | 3 KPI tiles (plan / actual / deviation) + **Plan vs Fact over Time** line chart + behind-schedule banner + project table |
| Project Detail | `/projects/:id` | Fixed header, 5 tabs: Overview · Stages & Tasks · Materials · Labor · Equipment |
| AI Chat | `/ai` | Full-height streaming chat (SSE), confirmation cards for write actions |
| Foreman Report | `/foreman-report` | Cascade selectors → materials / labor / equipment rows |

**Plan vs Fact over Time chart** (`BudgetTimelineChart`): pulls `GET /api/projects/{id}/budget-timeline` (or `/api/dashboard/budget-timeline` for the portfolio view). Shows a dashed plan line (step function derived from `date_start_plan`) and a solid actual line sourced from `budget_snapshots`. Dots on the actual line are colour-coded: 🔴 >10% overrun, 🟡 0–10%, 🟢 under plan. Project Detail adds a category switcher (Total / Materials / Labor / Equipment).

On mount the SPA calls `GET /api/whoami` to detect host: `standalone` enforces cookie auth, `bitrix` uses BX24 token and skips the login redirect.

### 6. Director Telegram Agent

The director can ask natural-language questions in Russian about any project directly in Telegram. The agent uses a **text-to-SQL** approach: it has access to the full schema description and generates SQL queries against the local SQLite database.

```
Director → Telegram message
  → POST /tg/webhook
    → chat_id checked against TELEGRAM_DIRECTOR_CHAT_IDS allowlist
    → app/telegram_agent.py: OpenRouter (openai/gpt-4.1-mini) tool-use loop
        → 2 tools:
            ├─ list_projects()         — returns [{id, name}] for project name resolution
            └─ query_database(sql)     — executes any SELECT against SQLite, returns rows as JSON
        → LLM generates SQL based on SCHEMA_DOCS (db/schema_docs.py) embedded in system prompt
        → results formatted as Russian answer → back to Telegram
```

**Example queries:**
- «Что закупили для ЖК Питер?» → `qty_bought` per material with units
- «Сколько топлива на складе?» → `qty_stock` for fuel rows
- «Есть ли перерасход на ЖК Питер?» → phases where `total_actual > total_plan`
- «Какие задачи просрочены?» → tasks where `date_end_plan < date('now')` and `completion_pct < 100`
- «Всё нормально на объекте?» → compact status summary (≤5 lines), not a full dump

**Safety**: `query_database` only accepts SELECT statements; non-SELECT returns an error. `LIMIT 200` is appended automatically if absent.

**SQLite custom functions** registered on every connection (see `db/database.py`):
- `py_lower(text)` — Unicode-aware LOWER that correctly handles Cyrillic (built-in SQLite `LOWER()` only handles ASCII A-Z)

**Schema docs** (`db/schema_docs.py`) embed column semantics into the agent prompt:
- `qty_bought` = purchased (arrived at warehouse); `qty_consumed` = used on site; `qty_stock` = remaining
- Phase names have a numeric prefix (`"3. Фундамент"`) — use substring search: `py_lower(phase) LIKE '%фундамент%'`
- Materials are stored per (phase, task_name) — use `SUM() GROUP BY material_name` for project totals

**QA test suite**: `scripts/test_agent_qa.py` runs the 15 base questions plus, with `--extended`, 9 edge-case questions (missing project, empty phase data, project budget total, phase ranking, etc.). Each tagged question runs a sanity check against the live SQLite DB and the script exits non-zero on any failure. A run log is written to `/tmp/agent_qa_<ts>.log`.

```bash
# On VPS:
venv/bin/python3 scripts/test_agent_qa.py             # base 15
venv/bin/python3 scripts/test_agent_qa.py --extended  # base + edge cases (24)
```

**Budget aggregation gotcha**: `budget_phases.total_plan` / `total_actual` may be `0` even when the per-component columns (`materials_plan`, `labor_plan`, `equipment_plan`) are populated — the original Bitrix-list keyword match for "итого план" can miss. Always read totals via `COALESCE(NULLIF(total_plan,0), materials_plan+labor_plan+equipment_plan)`. The migration scripts ([scripts/migrate_bitrix_to_sqlite.py](scripts/migrate_bitrix_to_sqlite.py), [scripts/import_excel.py](scripts/import_excel.py)) now apply the same fallback at write time, but pre-existing rows need a one-shot heal:

```sql
UPDATE budget_phases
SET total_plan   = COALESCE(NULLIF(total_plan,0),   materials_plan+labor_plan+equipment_plan),
    total_actual = COALESCE(NULLIF(total_actual,0), materials_actual+labor_actual+equipment_actual);
```

**Adding write tools** (future): register a new entry in `TOOL_REGISTRY` in `app/telegram_agent.py` with a JSON schema dict and an async handler. The agent loop picks it up automatically.

---

## Project Structure

```
frontend/
  src/
    pages/              # DashboardPage, ProjectDetailPage, AiPage, ForemanPage
    components/
      BudgetTimelineChart.tsx   # Plan vs Fact line chart (Recharts ComposedChart)
      dashboard/        # KpiTile, ProjectTable
      project/tabs/     # OverviewTab, StagesTab, MaterialsTab, LaborTab, EquipmentTab
      chat/             # ChatPanel, MessageBubble, ConfirmActionCard
    lib/
      api.ts            # Typed fetch wrappers for all /api/* endpoints
  vite.config.ts        # Dev server proxies /api/* → localhost:8000

bitrix/
  client.py              # All Bitrix24 HTTP calls go here. Handles rate limiting
                         # (0.5s interval + retry on QUERY_LIMIT_EXCEEDED × 5)
  methods/
    lists.py             # Universal Lists CRUD + field resolution helpers
    tasks.py             # CRM task create + UF_ETAP custom field setup
    workgroups.py        # Project (sonet group) creation

db/
  schema.sql             # CREATE TABLE statements — includes budget_snapshots (project_id, date, mat/lab/eq/total_actual)
  database.py            # init_db() + get_db() async context manager; registers py_lower(); runs migrations
  repo.py                # Thin async query helpers (upsert_*, get_*, cascade_update_*)
  schema_docs.py         # SCHEMA_DOCS string — embedded in Telegram agent system prompt

scripts/
  import_excel.py        # ExcelImporter class — full import orchestrator; dual-writes to SQLite
  migrate_bitrix_to_sqlite.py  # One-time backfill: reads all Bitrix lists → populates SQLite
  test_agent_qa.py       # Runs all 15 QA questions against the live agent (patches Telegram send)
  seed_demo_data.py      # Seeds 3 demo projects with phases, tasks, and 17 weekly budget_snapshots (S-curve ramp)

utils/
  excel_parser.py        # Reads .xlsx, detects header rows, returns {sheet: [row_dicts]}
  cascade.py             # Plan vs actual cascade: reads from SQLite, writes back to Bitrix mirror

app/
  webhook_handler.py     # FastAPI app — all HTTP endpoints
  bitrix_app.py          # Bitrix24 iframe install/widget routes + HTML form
  approval_page.py       # External /approval/{id} page + widget approval API
  _ui_styles.py          # Shared Procore-style design system: BASE_CSS, FONT_LINKS,
                         # status_pill(), severity_banner() — single source of truth
                         # consumed by bitrix_app.py and approval_page.py.
                         # Tokens & components mirror .stitch/DESIGN.md.
  telegram_agent.py      # Director AI agent: 2-tool text-to-SQL loop (list_projects + query_database)
  purchase_requests.py   # Procurement approval flow; reads/writes SQLite

docs/
  agent_test_questions.md  # 15 manual QA questions for the director Telegram agent

config.py                # Settings from .env (BITRIX24_WEBHOOK_URL, BITRIX24_DOMAIN, VPS_URL, DB_PATH)
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

# Seed demo data (3 projects + 17 weekly budget snapshots each)
python scripts/seed_demo_data.py

# Start the API server
uvicorn app.webhook_handler:app --reload --port 8000

# Start the React dev server (in a second terminal)
cd frontend && npm install && npm run dev
# → http://localhost:5173 (proxies /api/* to port 8000)
```

### Required `.env` keys

| Key | Description |
|-----|-------------|
| `BITRIX24_WEBHOOK_URL` | Full webhook URL including token |
| `BITRIX24_DOMAIN` | Portal domain (e.g. `mycompany.bitrix24.ru`) |
| `VPS_URL` | Public HTTPS URL of this server (Cloudflare tunnel URL) |
| `DB_PATH` | SQLite database file path (default: `/opt/buildcontrol/buildcontrol.db`) |
| `LOG_LEVEL` | `INFO` or `DEBUG` |

---

## VPS & Deploy

- **Server:** `<YOUR_VPS_IP>`, app at `/opt/buildcontrol/`, Python venv at `venv/`
- **Service:** `systemd` unit `buildcontrol` (uvicorn on port 8000, not exposed directly)
- **Public HTTPS:** Cloudflare Tunnel → temporary `*.trycloudflare.com` URL (changes on restart)

Deploy = rsync + **mandatory service restart** (uvicorn does not hot-reload Python modules):

```bash
cd "<project_dir>"

SSHPASS='<your_vps_password>' sshpass -e /usr/bin/rsync -avz \
  --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.git' --exclude='venv' --exclude='template_data' \
  -e "ssh -o StrictHostKeyChecking=no" \
  ./ root@<YOUR_VPS_IP>:/opt/buildcontrol/

ssh root@<YOUR_VPS_IP> "systemctl restart buildcontrol && systemctl status buildcontrol --no-pager"
```

See [prod_info.md](prod_info.md) for full ops details, Cloudflare tunnel setup, and troubleshooting.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/upload` | Upload `.xlsx` → pre-validates with openpyxl (400 on parse error) before scheduling background import |
| GET | `/api/whoami` | Returns `{ user, role, host, capabilities }` — SPA uses `host` to decide auth flow |
| GET | `/api/dashboard/summary` | Portfolio KPIs + per-project totals aggregated from `budget_phases` |
| GET | `/api/dashboard/budget-timeline` | Aggregated plan vs actual time series across all active projects |
| GET | `/api/projects` | List active (non-archived) workgroups |
| GET | `/api/projects/{id}/phases` | Phase budget rows (materials / labor / equipment plan vs actual) |
| GET | `/api/projects/{id}/budget-timeline` | Plan vs actual time series from `budget_snapshots`; anomaly annotation per point |
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
| GET | `/api/purchase-requests/{id}` | JSON detail for one request, with **per-item** graded severity (each item's price compared to its own plan price from "3. Материалы") |
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

## UI Design System

Every HTML surface (Bitrix24 widget tabs, install/rebind pages, external approval page) is rendered as inline f-strings inside Python — no Jinja, no static-files mount, no CSS framework. Visuals are unified through one shared module:

- **[`.stitch/DESIGN.md`](.stitch/DESIGN.md)** — design tokens, palette, typography, components, mobile breakpoint. Inspired by [Procore](https://www.procore.com).
- **[`app/_ui_styles.py`](app/_ui_styles.py)** — exports `BASE_CSS` (full stylesheet) and `FONT_LINKS` (IBM Plex Sans / Mono via Google Fonts). Both are concatenated into the `<head>` of every HTML response. Also exports helpers `status_pill(text, variant)` and `severity_banner(...)`.

Key tokens: Procore orange `#F47E42` for primary CTA, neutral grays as canvas, status semantics (success/warn/danger/info) for pills and severity banners. Mobile breakpoint at 768px collapses pill tabs to a fixed bottom nav, turns tables into stacked cards via `.bc-table--responsive`, grows inputs to 44px tap targets, and converts the primary submit into a sticky bottom bar.

**Editing visuals:** change `BASE_CSS` in `app/_ui_styles.py` and update `.stitch/DESIGN.md` in the same commit so the spec stays authoritative.

---

## Known Limitations

- `RESPONSIBLE_ID` and `CREATED_BY` on created tasks are hardcoded to user `1` (MVP)
- Cloudflare Tunnel URL changes on every restart — update `VPS_URL` in `.env`, restart the service, then call `GET /bitrix/rebind?domain=YOUR_DOMAIN&auth=AUTH_TOKEN` to re-register the LEFT_MENU widget without reinstalling the app
- No authentication on API endpoints — they're protected only by the VPS not being publicly linked
- Negative quantities in foreman reports are accepted and cascade through (e.g. `Объём израсходовано` goes negative); no input validation at the API layer
- `task.commentitem.getlist` returns `[]` via REST even after a successful `task.commentitem.add` — a known Bitrix24 REST API quirk; comments ARE posted (confirmed by the comment ID returned from `add`)
- Under ≥10 concurrent `/api/report` calls the Bitrix24 rate-limit retry budget (5×) can exhaust, causing HTTP 500. The normal single-foreman form usage is unaffected; multi-site concurrency would require raising `MAX_RETRIES` or queuing
- Buyer purchase **approval does NOT trigger cascade**. Approval only updates `Объём куплено` / `Остаток` / `Цена ед. факт` — none of which feed `Стоим. факт`. `Стоим. факт` is owned by the foreman daily report path (`Объём израсходовано` × price). Approving a purchase therefore intentionally leaves task/budget rollups unchanged
- Telegram inline buttons (✅ / ❌) **edit the original message in place** after a decision: the buttons are removed and a status line (e.g. `✅ Подтверждено — @user`) is appended to the message body, so the chat history shows the resolution
- The Excel importer **skips rows in "2. Этапы и задачи" with empty Этап** — a row with no phase has nowhere to roll into "1. Бюджет" and is treated as junk
- **SQLite materials are stored per (phase, task_name)** — if the same physical material (e.g. "Топливо") appears in multiple tasks, `SUM(qty_bought)` across rows produces the sum of per-task purchases. The Telegram agent uses `SUM() GROUP BY material_name` for project-wide totals, which is correct; but if two tasks happen to track the same physical stockpile, the numbers will appear doubled. This is a data modelling choice in the Excel template, not a bug.

## Bitrix UI Root-Only Filter (safe mode)

To hide subtasks from the main Tasks list/Kanban in standard Bitrix UI:

1. Open **Tasks and Projects** → project tasks list (or project Kanban)
2. Open **Filter + Search**
3. Add field **Parent task** and set it to **is empty**
4. Save filter (e.g. `Root tasks only`)
5. In filter settings, enable **Apply for all users** (public/shared filter)

Result: main list/Kanban shows only root tasks; subtasks remain visible inside parent task cards.
