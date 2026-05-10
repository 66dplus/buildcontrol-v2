# Effort Estimate — BuildControl v2 Roadmap

These numbers represent **active human-hours**: directing Claude, reviewing diffs, testing, decision-making. Claude generates code; 1–2 subagents handle parallelizable work (independent screens, independent tools, tests written alongside features). The Claude + subagents multiplier is already applied versus solo-engineer day estimates.

Rule of thumb used: 1 "engineer-day" of conventional work compresses to ~4–6 active human-hours when the human is driving Claude with parallel subagents.

→ See [docs/roadmap.md](roadmap.md) for the architecture and task descriptions referenced here.

---

## Wave 1 — Foundation + AI-first director surface (weeks 1–3)

| # | Task | Hours (low–high) | Subagent leverage |
|---|------|------------------|-------------------|
| 1 | Frontend scaffolding (Vite + Tailwind + FastAPI static serve, dual host loaders, auth abstraction, login screen) | 10–14 | Low — foundational, sequential |
| 2 | Director Dashboard v1 (layout shell, project list + KPI tiles, project detail w/ cascade view, Recharts burn-down) | 14–18 | High — KPI tiles + detail view in parallel |
| 3 | AI Chat web UI (SSE endpoint, React chat panel w/ streaming, markdown + table rendering, loading/error states) | 6–10 | Medium — UI and endpoint in parallel |
| 4 | AI write-action tools (4 tools × Bitrix integration, confirmation UI, audit log, tests) | 12–16 | High — 4 tools dispatched in parallel |
| 5 | Excel onboarding NL assignment (review screen, NL parsing tool, defer task creation until confirmed, ambiguous-name handling, tests) | 10–14 | Medium |
| 6 | Agent test coverage (tool dispatch, SQL guardrails, write-action confirmation flow, mocks) | 6–8 | Medium |
| **Wave 1 subtotal** | | **58–80** | |

## Wave 2 — Foreman/Buyer/Approver rebuild + voice (weeks 4–5)

| # | Task | Hours (low–high) | Subagent leverage |
|---|------|------------------|-------------------|
| 7 | Foreman report screen in React (form rebuild, optimistic UI, error toasts, parity tests with current widget) | 10–14 | Medium |
| 8 | Buyer + Approval screens in React (rebuild both, share form components from #7) | 8–10 | High — both in parallel after components extracted |
| 9 | Voice mode (push-to-talk UI, browser audio capture, OpenRouter STT proxy, OpenRouter TTS proxy, audio playback, Russian language hint tuning) | 8–12 | Medium — STT and TTS endpoints in parallel |
| 10 | Performance pass (parallelize independent Bitrix calls, background queue, frontend optimistic UI integration) | 6–10 | Medium |
| **Wave 2 subtotal** | | **32–46** | |

## Wave 3 — Differentiation + production hardening (weeks 6–8)

| # | Task | Hours (low–high) | Subagent leverage |
|---|------|------------------|-------------------|
| 11 | Proactive AI (watchdog prompt, nightly scheduler, anomaly classification, dashboard banner, Telegram push, tests) | 14–18 | Medium |
| 12 | Security hardening (iframe signature, token exchange endpoint, rate limiting, CORS tightening, secrets audit, light pen-test) | 10–14 | Medium |
| 13 | Mobile polish (Bitrix mobile app testing, responsive fixes, touch-target audit) | 4–8 | Low — manual testing dominates |
| 14 | Onboarding format polish (Excel validation w/ friendly errors, progress indicator, retry-step UI) | 6–10 | Medium |
| **Wave 3 subtotal** | | **34–50** | |

---

## Totals

| Scope | Hours (low–high) | Calendar @ 4h/day | Calendar @ 6h/day |
|-------|------------------|-------------------|-------------------|
| Wave 1 | 58–80 | 15–20 days | 10–13 days |
| Wave 2 | 32–46 | 8–12 days | 5–8 days |
| Wave 3 | 34–50 | 9–13 days | 6–9 days |
| **Total** | **124–176** | **32–45 days** | **21–30 days** |

---

## Reality check

Claude + subagents do not eliminate review and testing time, which is the bottleneck.

Calendar estimates assume:
- Disciplined daily work (no multi-day gaps).
- No major Bitrix API surprises.
- Willingness to ship Wave 1 before perfecting it.

Likely overrun triggers:
- Russian transcription accuracy via OpenRouter Whisper poor on construction-site audio → +2–4h on task #9 to swap models or tune language hints.
- Agent's write tools surface an unexpected Bitrix permission edge case → +4–6h on task #4.
- Frontend scaffolding decisions (state management, routing) trigger rework → +4–8h on task #1, propagating into tasks #2, #3.

This document should be updated as work progresses. Mark tasks done with their actual hours; note overruns with cause. Effort accuracy improves the most when actuals are tracked early.
