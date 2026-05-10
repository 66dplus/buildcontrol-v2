# BuildControl v2 — Roadmap to a Real AI-First Product

## Context

BuildControl v2 today is a functional MVP: foreman/buyer/approver workflows in a Bitrix24 iframe widget, a read-only Telegram-only director agent, hardcoded employee assignment, and meaningful security/performance debt. The goal over the next 6–8 weeks is to evolve this into a real, production-ready, AI-first construction control product. An investor presentation in 2–3 weeks uses slides + a recorded video, so the bar is "real working product the video can show honestly," not "live demo polish."

Two strategic decisions are locked in:

- **One frontend, two hosts.** A single React + Vite + Tailwind SPA is served from FastAPI, mounted both as a standalone web app (login auth) and inside the existing Bitrix24 iframe (token auth). Both hosts share the same UI, same AI features, same code.
- **No existing users to protect.** We can refactor aggressively. The current widget can be replaced rather than extended.

Intended outcome at the end of 6–8 weeks: a director can log in to either surface, see a real dashboard with KPIs and budget cascades, talk to the AI agent in chat or voice, have it answer with structured data AND take actions in Bitrix24 (create tasks, comment, assign, advance stages), receive proactive anomaly alerts, and onboard a new project from Excel + natural-language employee assignment in minutes instead of hardcoded values.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  React + Vite + Tailwind SPA  (one codebase)        │
│  - Director Dashboard, AI Chat, Voice               │
│  - Foreman/Buyer/Approver screens (rebuilt)         │
└──────────────────┬──────────────────────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
  Standalone host         Bitrix iframe host
  (login auth)            (BX24 token auth)
       │                       │
       └──────────┬────────────┘
                  ▼
         FastAPI backend
         ├─ /api/* (existing endpoints)
         ├─ /api/agent/chat   (NEW — SSE streaming)
         ├─ /api/agent/voice  (NEW — STT/TTS via OpenRouter)
         └─ Bitrix24 REST + SQLite mirror
```

Key principle: **one frontend, two hosts, one auth abstraction**. The SPA does not know which host it is in until it calls `/api/whoami`, which returns `{user, role, capabilities, host}`. This is the cheapest way to keep the surfaces in sync.

### Critical files to be modified or created

- [app/bitrix_app.py](../app/bitrix_app.py) (1,811 LOC) — most of this gets deleted; the route handlers stay but return the new SPA shell instead of inline HTML. `_ui_styles.py` is retired.
- [app/auth.py](../app/auth.py) — extended with a second auth path: standalone login (cookie/JWT) alongside the iframe bearer-token path it already handles.
- [app/telegram_agent.py](../app/telegram_agent.py) — extracted into a generic `app/agent/` package; Telegram becomes one of three surfaces (Telegram, web chat SSE, voice). Tools registry grows from 2 read-only tools to ~6 tools, several of which write.
- [scripts/import_excel.py](../scripts/import_excel.py) line 508 — `responsible_id=1` hardcode removed; assignments come from the new NL onboarding step.
- New: `frontend/` directory with React + Vite + Tailwind project. Built output served as static from FastAPI.
- New: `app/agent/tools/` — `create_task.py`, `add_comment.py`, `assign_user.py`, `move_task_stage.py`, audit logging.
- New: `app/agent/voice.py` — STT + TTS via OpenRouter audio endpoints (`/api/v1/audio/transcriptions` for Whisper, `/api/v1/audio/speech` for TTS). Single OpenRouter API key already in use covers chat + voice in + voice out.
- New: `db/migrations/` — anomaly digests, audit log tables.

### Existing utilities to reuse (do NOT reinvent)

- [bitrix/client.py](../bitrix/client.py) for all Bitrix24 calls (rate limiting + retries already in place).
- [utils/cascade.py](../utils/cascade.py) for budget recomputation.
- [db/schema_docs.py](../db/schema_docs.py) already feeds the agent's system prompt — the same pattern extends to write-tool documentation.
- [bitrix/methods/tasks.py](../bitrix/methods/tasks.py) already accepts `responsible_id`; we just need to start passing real values to it.

---

## Phased roadmap (6–8 weeks, three waves)

### Wave 1 — Foundation + AI-first director surface (weeks 1–3)

This is what the investor video shows.

1. **Frontend scaffolding.** React + Vite + Tailwind, served as static from FastAPI. Dual host loaders for standalone vs iframe. Auth abstraction (`useAuth()` works in both contexts).
2. **Director Dashboard v1.** Project list with KPI tiles (план/факт/% выполнения/anomalies), project detail (cascade view of phases/tasks/budget), Recharts for budget burn-down.
3. **AI Chat in the web UI.** Move the existing `telegram_agent.py` behind `POST /api/agent/chat` with SSE streaming. Same agent, new surface. Frontend chat panel with markdown rendering, inline tables and small charts for tool results.
4. **AI write-action tools.** Add `create_task`, `add_comment`, `assign_user`, `move_task_stage` to the agent's tool registry. All go through Bitrix REST + mirror to SQLite. Each write tool requires an explicit confirmation step in the UI before executing. Audit log table records every action.
5. **Excel onboarding with NL assignment.** During import, after stages/tasks are parsed, show a review screen. Director types or speaks "Алексея на стадии 1–3, Андрея на фундамент"; agent parses and assigns `responsible_id` per task before creation. Removes the hardcode in `scripts/import_excel.py:508`.
6. **Test coverage for the agent.** Wave 1 ships zero agent tests today. Cover tool dispatch, SQL guardrails, write-action confirmation flow, ambiguous-name resolution.

### Wave 2 — Foreman/Buyer/Approver rebuild + voice (weeks 4–5)

7. **Foreman report screen in React.** Replace the inline-JS form. Optimistic UI: "saved ✓" returns immediately, cascade runs in a background task, failures surface as toast. Fixes the 4–6s perceived latency.
8. **Buyer + Approval screens in React.** Same rebuild pattern.
9. **Voice mode.** Push-to-talk button next to the chat input. Browser records audio → POST to `/api/agent/voice/transcribe` → server forwards to OpenRouter `/api/v1/audio/transcriptions` (Whisper Large V3 Turbo, Russian language hint) → transcript fed into existing chat agent → response text → POST to `/api/agent/voice/speak` → OpenRouter `/api/v1/audio/speech` returns audio → played in browser. Single provider (OpenRouter) for chat + STT + TTS.
10. **Performance pass.** Parallelize the 8–12 Bitrix calls in the cascade path where they are independent. Small in-memory background queue so report POST returns in <500ms.

### Wave 3 — Differentiation + production hardening (weeks 6–8)

11. **Proactive AI.** Nightly job runs the agent in "watchdog mode" per project — generates an anomalies digest (budget overruns, silent foremen, equipment cost spikes). Surfaces as a dashboard banner + Telegram push. Strongest single AI-first differentiator.
12. **Security hardening.** Bitrix iframe signature verification, move bearer token out of HTML (token exchange endpoint), rate limiting on public endpoints, tighten CORS, secrets audit.
13. **Mobile polish for Bitrix.** Test inside the Bitrix24 mobile app, fix responsive issues that surface there.
14. **Onboarding format polish.** Excel template validation with friendly errors before import starts, per-step progress indicator, retry-a-single-step UI.

### Explicit cuts / deferrals

- Multi-tenancy.
- Custom in-app role management (Bitrix24 user roles map through directly).
- Separate notifications hub (Telegram + dashboard banner are enough).
- Switching off Bitrix as the source of truth.

---

## Top risks

1. **Voice mode reliability.** Russian STT in noisy construction environments via Whisper Large V3 Turbo may degrade. Mitigation: text input always available alongside voice; voice is enhancement, not gate. If accuracy is poor, swap the OpenRouter transcription model (GPT-4o Transcribe or Groq Whisper) without changing the integration shape.
2. **Write-action safety.** Agent making destructive CRM changes. Mitigation: mandatory confirmation step in UI, audit log in SQLite, no destructive operations (no task delete, no archive) in v1.
3. **Two hosts diverging.** Discipline-only risk. Mitigation: shared auth abstraction; one SPA, never branch per host; CI builds both contexts.
4. **Bitrix rate limiting under parallelization.** Going from sequential to parallel calls in cascade may exhaust the per-webhook 2 req/sec budget. Mitigation: respect existing 0.5s minimum interval in `bitrix/client.py`; parallelize only across distinct logical batches, not within them.

---

## Verification

For each wave, before declaring complete:

- **Wave 1.** End-to-end: log in to standalone host → upload Excel → assign people in NL → see project on dashboard → ask agent in chat to "create a task for Alexey for foundation rework" → confirm → task appears in Bitrix CRM with correct assignee. Repeat in Bitrix iframe host. All agent tests pass.
- **Wave 2.** Submit a foreman report from a phone-sized viewport in <1s perceived latency; cascade visible in dashboard within 5s. Voice command "покажи перерасходы за неделю" returns spoken + on-screen answer. All existing report tests still pass.
- **Wave 3.** Wake up to a Telegram digest of overnight anomalies for one test project. Run a basic security scan against the production endpoint with no high findings. Open the standalone web app inside the Bitrix24 mobile app and complete a foreman report flow.

---

→ See [docs/effort-estimate.md](effort-estimate.md) for per-task hour estimates and calendar projections.
