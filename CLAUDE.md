# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repo.

## Role

You maintain BuildControl — a construction project-control system with a
Bitrix24-REST + FastAPI backend and a React (Vite + Tailwind + Recharts)
frontend. Both halves are first-class. Write working code, test every
step, confirm before moving on.

## Architecture

The **Subsystems** section in [README.md](README.md) is the canonical map.
At a glance: Bitrix24 client + universal-list domain (`bitrix/`), FastAPI
routes (`app/routes/`), local SQLite mirror (`db/`), agent with tool
registry + SSE streaming (`app/agent/`), procurement workflow
(`app/purchase_requests.py`), notifications (`app/notifications/`),
Excel import (`scripts/import_excel.py`), React SPA (`frontend/`).

## MCP Tools

- **`bitrix24-docs`** — Official Bitrix24 REST docs. Use it instead of
  guessing API params, return values, or auth.

## Code style

- Python: type hints on every function. Use `httpx` (not `requests`).
  All Bitrix24 calls go through `bitrix/client.py` — never call the
  API directly.
- TypeScript: follow the patterns already in `frontend/src/lib/api.ts`
  and existing pages/tabs. New API methods get typed input + output.
- Log to stdout with timestamps. No silent failures.

## Bitrix24 client gotchas

- **Rate limit**: 2 req/sec per webhook. `bitrix/client.py` enforces
  0.5s spacing + 5× exponential backoff on `QUERY_LIMIT_EXCEEDED`.
  Fine for sequential use; not safe under ≥10 concurrent report POSTs.
- **`find_elements_by_properties()` keyword match is partial+CI**.
  Pitfall: sheet "2. Этапы и задачи" has both `"Готовн. план, %"` and
  `"Готовн. факт, %"` — always use `"готовн. факт"`, not `"готовн"`,
  or you'll write to the plan column.
- **Stage `SYSTEM_TYPE` is null** for custom kanban stages. Derive by
  position: index 0 → `NEW` (Новая), last index → `FINISH` (Завершена),
  middle → `PROGRESS`. Drives lifecycle calls and
  `Дата нач. факт` / `Дата ок. факт` writes.

## Commands

```bash
# Backend
pip install -r requirements.txt
python -m pytest tests/ -v
python scripts/import_excel.py template_data/plan_fact_v4.xlsx

# Frontend
cd frontend && npm install && npm run dev
npm run test
```

## Deploy

See [prod_info.md](prod_info.md) for the rsync + `systemctl restart
buildcontrol` procedure and Cloudflare-tunnel setup.
**Critical**: uvicorn does NOT hot-reload Python — `systemctl restart
buildcontrol` is mandatory after every code deploy.

## Critical rules

- NEVER commit `.env`.
- NEVER guess Bitrix24 API params — use `bitrix24-docs` MCP first.
- After every VPS deploy: `systemctl restart buildcontrol`.
- When adding an env var, also update `.env.example`.

## Documentation

After every behaviour-visible change, update [README.md](README.md)
(developer-facing) and [prod_info.md](prod_info.md) (ops). Skip only
for pure internal refactors.
