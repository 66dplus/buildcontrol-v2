# BuildControl — Production Info

> **Audience:** Anyone deploying, maintaining, or debugging this app on the VPS.  
> **Last updated:** 2026-04-26

---

## Server

| Property | Value |
|---|---|
| Provider | Hostkey (hk) |
| IP | `162.120.19.127` |
| OS | Ubuntu 24.04.4 LTS |
| RAM | 1.8 GB |
| Disk | 58 GB (8.6 GB used) |
| SSH user | `root` |

### SSH access

```bash
ssh root@162.120.19.127
# password stored in .env as VPS_PASSWORD
```

---

## App

| Property | Value |
|---|---|
| Location on server | `/opt/buildcontrol` |
| Python | 3.12.3 (virtualenv at `/opt/buildcontrol/venv`) |
| Web framework | FastAPI + Uvicorn |
| Listens on | `http://localhost:8000` (not exposed directly) |
| Public URL | Cloudflare Tunnel (see below) |
| SQLite DB | `/opt/buildcontrol/buildcontrol.db` |

### Config file

The app reads secrets from `/opt/buildcontrol/.env` on the server.  
**This file is NOT in git** — you must set it up manually on a new server.

Required keys:

```env
BITRIX24_WEBHOOK_URL=https://<domain>.bitrix24.com/rest/1/<token>/
BITRIX24_DOMAIN=<domain>.bitrix24.com
VPS_URL=https://<cloudflare-tunnel-url>.trycloudflare.com
DB_PATH=/opt/buildcontrol/buildcontrol.db
LOG_LEVEL=INFO

# Telegram notifications (optional — app works without them)
TELEGRAM_BOT_TOKEN=<token from @BotFather>
TELEGRAM_CHAT_ID=<chat or group ID>
NOTIFICATIONS_ENABLED=false
```

Template is in `.env.example` in the repo.

---

## Systemd Service

The app runs as a systemd service called `buildcontrol`.

### Common commands

```bash
# Check if the app is running
systemctl status buildcontrol

# Restart after a code deploy
systemctl restart buildcontrol

# See live logs
journalctl -u buildcontrol -f

# See last 100 log lines
journalctl -u buildcontrol -n 100 --no-pager

# Stop / Start
systemctl stop buildcontrol
systemctl start buildcontrol
```

### Service definition

File lives at `/etc/systemd/system/buildcontrol.service` and is also committed to the repo as `buildcontrol.service`.

If you ever change the `.service` file:
```bash
systemctl daemon-reload
systemctl restart buildcontrol
```

---

## Public HTTPS Tunnel (Cloudflare)

The VPS has no domain name or SSL certificate. Instead, **Cloudflare Tunnel** (`cloudflared`) creates a temporary HTTPS URL that proxies to `localhost:8000`.

### Current status

Cloudflared is running as a **bare background process** (not a systemd service).  
Started with:
```bash
cloudflared tunnel --url http://localhost:8000 --no-autoupdate &
```

### ⚠️ Known issue: URL changes on restart

The tunnel uses a **free temporary URL** (`*.trycloudflare.com`).  
**Every time cloudflared restarts, the URL changes.**

After a server reboot or cloudflared restart:
1. Run `cloudflared tunnel --url http://localhost:8000 --no-autoupdate &`
2. Wait ~5 seconds, then check the new URL in the output or with:
   ```bash
   journalctl | grep trycloudflare
   ```
   or
   ```bash
   ps aux | grep cloudflared
   # then check logs:
   cloudflared tunnel --url http://localhost:8000 --no-autoupdate 2>&1 | head -20
   ```
3. Update the Bitrix24 app handler URL in the Bitrix24 admin panel
4. Update `VPS_URL` in `/opt/buildcontrol/.env`
5. Restart the app: `systemctl restart buildcontrol`

### Fix: make cloudflared a proper service

To avoid the above problem, create a systemd service for cloudflared:

```bash
# On the server:
cat > /etc/systemd/system/cloudflared.service << 'EOF'
[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/cloudflared tunnel --url http://localhost:8000 --no-autoupdate
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cloudflared
systemctl start cloudflared
```

Note: URL will still change if cloudflared restarts. For a **stable URL**, upgrade to a named Cloudflare Tunnel with a real domain (requires a free Cloudflare account + domain).

---

## SQLite Database

The app uses SQLite as its primary read database. Bitrix24 lists are kept as a display mirror.

| Path | `/opt/buildcontrol/buildcontrol.db` |
|---|---|
| Tables | `projects`, `tasks`, `materials`, `labor`, `equipment_items`, `budget_phases`, `purchase_requests` |
| Populated by | `scripts/import_excel.py` (dual-write on import) + report/purchase webhooks |

### Inspect the database

```bash
sqlite3 /opt/buildcontrol/buildcontrol.db

# Row counts per table
SELECT 'projects', COUNT(*) FROM projects UNION ALL
SELECT 'tasks', COUNT(*) FROM tasks UNION ALL
SELECT 'materials', COUNT(*) FROM materials UNION ALL
SELECT 'purchase_requests', COUNT(*) FROM purchase_requests;

# Check fuel stock across all projects
SELECT p.name, m.material_name, m.qty_stock, m.unit
FROM materials m JOIN projects p ON p.id = m.project_id
WHERE lower(m.material_name) LIKE '%топливо%';
```

### One-time migration (first deploy or new server)

After deploying code to a server that has existing Bitrix data but an empty SQLite DB, run:

```bash
cd /opt/buildcontrol
venv/bin/python3 scripts/migrate_bitrix_to_sqlite.py
```

This reads all projects and their 5 Universal Lists from Bitrix and inserts them into SQLite. Safe to re-run — uses `INSERT OR REPLACE` (idempotent). Takes ~30s per project due to Bitrix rate limiting.

### Director AI agent QA

Run the benchmark to verify the agent generates correct SQL. Use `--extended` to add 9 edge-case questions and automated DB sanity checks (exit code != 0 on any failure):

```bash
cd /opt/buildcontrol
venv/bin/python3 scripts/test_agent_qa.py             # 15 base
venv/bin/python3 scripts/test_agent_qa.py --extended  # 24 total + sanity checks
```

Each run writes a transcript to `/tmp/agent_qa_<ts>.log`.

**If the agent reports "0 ₽ из 0 ₽" for a project**, the legacy `budget_phases.total_plan` rows are missing. Heal the live DB once:

```bash
venv/bin/python3 - <<'PY'
import sqlite3
c = sqlite3.connect("/opt/buildcontrol/buildcontrol.db")
c.execute("""UPDATE budget_phases
             SET total_plan   = COALESCE(NULLIF(total_plan,0),   materials_plan+labor_plan+equipment_plan),
                 total_actual = COALESCE(NULLIF(total_actual,0), materials_actual+labor_actual+equipment_actual)""")
c.commit()
PY
```

Future imports already apply the fallback at write time (see migration script and Excel importer).

---

## Deploy: Update the App

Use this whenever you push new code changes.

### Option A — one-liner from your Mac

```bash
cd "/Users/dmitrijrybkin/Documents/Claude Code/BuildControl_v2"

# 1. Copy files to server (skips .env, cache, git, venv)
SSHPASS='<password>' sshpass -e /usr/bin/rsync -avz \
  --exclude='.env' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='template_data' \
  -e "ssh -o StrictHostKeyChecking=no" \
  ./ root@162.120.19.127:/opt/buildcontrol/

# 2. Restart the service
ssh root@162.120.19.127 "systemctl restart buildcontrol && systemctl status buildcontrol --no-pager"
```

### Option B — manual on the server

```bash
ssh root@162.120.19.127
cd /opt/buildcontrol

# Pull latest code (if you set up git on the server)
git pull

# Or copy files manually with scp, then:
systemctl restart buildcontrol
```

---

## Install from Scratch (new server)

If you ever need to set up on a new VPS:

```bash
# 1. SSH into new server
ssh root@<NEW_IP>

# 2. Install system deps
apt-get update && apt-get install -y python3 python3-venv python3-pip rsync

# 3. Create app directory
mkdir -p /opt/buildcontrol

# 4. Copy code (from your Mac)
rsync -avz \
  --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.git' --exclude='venv' \
  ./ root@<NEW_IP>:/opt/buildcontrol/

# 5. Create virtualenv and install deps
cd /opt/buildcontrol
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 6. Create .env (copy from .env.example, fill in real values)
cp .env.example .env
nano .env

# 7. Install and start the systemd service
cp buildcontrol.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable buildcontrol
systemctl start buildcontrol

# 8. Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# 9. Start tunnel and note the URL
cloudflared tunnel --url http://localhost:8000 --no-autoupdate &
# Look for: "Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):"

# 10. Update VPS_URL in .env with the new URL
# 11. Update Bitrix24 app handler URL in Bitrix24 admin
```

---

## Health Check

```bash
# Quick check from your Mac:
curl https://<VPS_URL>/health
# Expected: {"status":"ok","service":"BuildControl Upload API"}

# Or on the server directly:
curl http://localhost:8000/health
```

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check |
| POST | `/upload` | Upload .xlsx → pre-validates with openpyxl (returns 400 on parse error) before scheduling background import |
| GET | `/api/projects` | List active (non-archived) projects |
| GET | `/api/projects/{id}/tasks` | Root tasks from project's "2. Этапы и задачи" list (deduplicated) |
| GET | `/api/projects/{id}/stages` | Kanban stages for the project workgroup |
| GET | `/api/projects/{id}/task-context` | Combined task payload (`materials`, `labor`, `equipment`, `subtasks`) for `?etap=X&zadacha=Y` |
| GET | `/api/projects/{id}/materials` | Materials from project's "3. Материалы" list |
| GET | `/api/projects/{id}/labor` | Workers from project's "4. Трудозатраты" list |
| GET | `/api/projects/{id}/equipment` | Equipment from project's "5. Техника" list |
| GET | `/api/projects/{id}/subtasks` | Subtasks for a task (`?etap=X&zadacha=Y`); empty for v3 projects |
| POST | `/api/report` | Save foreman daily report + trigger notifications |
| POST | `/api/buyer-report` | **Deprecated (HTTP 410)** — points to `/api/purchase-request` |
| POST | `/api/purchase-request` | Submit a procurement approval request (multipart, REQUIRED `proposal` PDF, REQUIRED `buyer_comment` if any item priced over plan) |
| GET | `/api/purchase-requests/pending` | List pending requests across projects (used by widget Согласование tab) |
| GET | `/api/purchase-requests/{id}` | JSON detail with **per-item** graded severity (each item compared to its own plan price from "3. Материалы") |
| POST | `/api/purchase-requests/{id}/decide` | Apply approve / reject / comment from the widget (no token) |
| GET | `/approval/{id}` | External approval page (token-signed link, opened from Telegram backwards-compat) |
| GET | `/approval/{id}/state` | Polling endpoint used by approval page |
| POST | `/approval/{id}/decide` | Apply approve / reject / comment from the external page |
| POST | `/tg/webhook` | Telegram bot webhook (callback_query + comment follow-up) |
| POST | `/api/test-digest` | Manually trigger morning digest (for testing) |
| GET | `/bitrix/install` | Bitrix24 app install page |
| GET | `/bitrix/widget` | Bitrix24 iframe widget |
| GET | `/bitrix/rebind` | Re-register LEFT_MENU placement after tunnel URL change |

---

## UI / Visual Design

All HTML surfaces (widget tabs, approval page, install/rebind) share a single Procore-inspired stylesheet defined in `app/_ui_styles.py` (`BASE_CSS` + `FONT_LINKS`). Spec lives in `.stitch/DESIGN.md`.

- **No new runtime deps.** Styles are still inlined into the HTML response — same deploy story (rsync + `systemctl restart buildcontrol`).
- **Outbound network:** the `<head>` includes a Google Fonts `<link>` for IBM Plex Sans / Mono. If the VPS or the user's browser cannot reach `fonts.googleapis.com`, the CSS falls back to the system font stack (`-apple-system, Segoe UI, Roboto, ...`) — visuals degrade gracefully.
- **Mobile breakpoint** at 768px collapses the foreman widget tabs to a fixed bottom nav and converts wide tables to stacked cards. Verify after each deploy by opening the widget URL in Chrome DevTools' device toolbar.

---

## Telegram Notifications

The app sends alerts and a daily digest to Telegram when `NOTIFICATIONS_ENABLED=true`.

### Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) → copy the token
2. Add the bot to a group chat (or message it directly)
3. Get the chat ID (send a message, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`)
4. Set env vars in `/opt/buildcontrol/.env`:
   ```
   TELEGRAM_BOT_TOKEN=<token>
   TELEGRAM_CHAT_ID=<chat_id>
   NOTIFICATIONS_ENABLED=true
   ```
5. Restart: `systemctl restart buildcontrol`

### Director AI agent (natural-language project queries)

The director can send messages in Russian to the bot to query any project's status.

**Required env vars** (add to `/opt/buildcontrol/.env`):
```
OPENROUTER_API_KEY=sk-or-v1-...        # from openrouter.ai → Keys
OPENROUTER_MODEL=openai/gpt-4.1-mini   # or any OpenRouter model supporting tool_use
TELEGRAM_DIRECTOR_CHAT_IDS=753647644   # comma-separated, director's Telegram chat id(s)
```

After setting these, restart: `systemctl restart buildcontrol`.

Messages from non-listed chat IDs are silently ignored by the bot.

### Procurement approval webhook

For the procurement approval flow (`/api/purchase-request`), the bot also acts as
an inline-button surface. Set the additional env vars:

```
APPROVAL_LINK_SECRET=<32+ char random string>
TELEGRAM_WEBHOOK_SECRET=<random string>
TELEGRAM_APPROVER_CHAT_ID=<chat id, defaults to TELEGRAM_CHAT_ID>
PURCHASE_APPROVER_USER_ID=<Bitrix user id>
MAX_PROPOSAL_FILE_MB=10
```

Register the webhook with Telegram once after deploy:

```bash
curl -F "url=$VPS_URL/tg/webhook" \
     -F "secret_token=$TELEGRAM_WEBHOOK_SECRET" \
     "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook"
```

Per-project Bitrix24 Disk folder `Заявки на закупку` and the `Заявки на закупку`
universal list are both created lazily by the backend on first purchase request —
no migration script is required for existing projects.

### Alert types

| Alert | Trigger | When |
|-------|---------|------|
| Price overrun | `Цена ед. факт > Цена ед. план` | After purchase-request approval |
| Disproportionate consumption | Material consumed faster than work progresses (cross-task) | After foreman report |
| Low warehouse stock | Stock < 20% of planned volume | After foreman report |
| Budget threshold | Budget > 80% spent but task < 70% complete | After cascade update |
| Schedule slippage | Expected completion > actual by 20+ percentage points | After foreman report |
| Subtask overdue | Non-completed subtask with `Дата ок. план < today` | After foreman report (v4 projects) |
| No-report | Active project with no reports yesterday | Daily digest (9:00 MSK) |
| Morning digest | Summary of all yesterday's activity across all projects | Daily at 9:00 MSK |

### Testing

```bash
# Manually trigger the morning digest:
curl -X POST https://<VPS_URL>/api/test-digest
```

---

## Bitrix UI: show only root tasks

New imports (after 2026-04-25) do **not** create Bitrix child tasks for subtasks — the native task list and Kanban will only contain the 22 parent tasks automatically.

For projects imported before that date (which have Bitrix child tasks for subtasks), apply this filter once per project:

1. Open project **Tasks** list or **Kanban**
2. Click **Filter + Search**
3. Add filter field **Parent task**
4. Set condition to **is empty**
5. Save filter as `Root tasks only`
6. In filter settings, enable **Apply for all users**

---

## Troubleshooting

| Problem | What to do |
|---|---|
| App not responding | `systemctl status buildcontrol` → check if running |
| App crashed | `journalctl -u buildcontrol -n 50 --no-pager` → read the error |
| Bitrix24 can't reach app | Check tunnel: `ps aux \| grep cloudflared` — if missing, restart it |
| URL changed | See "⚠️ Known issue" section above |
| Import fails with 500 | Check logs: `journalctl -u buildcontrol -f` then retry the upload |
| Import returns 400 immediately on upload | The pre-validation guard rejected the file as not a valid xlsx; re-export from Excel and retry |
| Port 8000 not listening | `ss -tlnp \| grep 8000` — if empty, app is down |
| Director Telegram bot silent | (1) `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo` — check `last_error_message`. (2) `journalctl -u buildcontrol --since '10 min ago'` — common causes: `ModuleNotFoundError: No module named 'openai'` (run `/opt/buildcontrol/venv/bin/pip install -r /opt/buildcontrol/requirements.txt`); chat_id not in `TELEGRAM_DIRECTOR_CHAT_IDS`; `OPENROUTER_API_KEY` missing |
| Agent answers wrong numbers / "нет данных" unexpectedly | SQLite may be empty or stale — run `scripts/migrate_bitrix_to_sqlite.py`. Also check `py_lower()` is registered: if you see `no such function: py_lower` in logs, the connection was opened without `db.database.get_db()` (e.g. direct aiosqlite call) |
| Agent shows `qty_consumed` instead of `qty_bought` for "что куплено" questions | Schema docs (`db/schema_docs.py`) didn't emphasize the distinction — verify the ВАЖНО block is present and re-deploy |
| Cyrillic LIKE returns empty results | SQLite built-in `LOWER()` does NOT handle Cyrillic. Always use `py_lower()` (registered as a custom function). The schema_docs examples all use `py_lower()` — if the agent generates bare `LOWER()` or bare `LIKE` it won't match Russian text |
| Approve/reject Telegram message buttons stay forever | Bot couldn't `editMessageText` — check `journalctl` for `Telegram editMessageText failed`. Most often the bot lacks edit permission in a group chat; promote it to admin or DM the bot directly |
