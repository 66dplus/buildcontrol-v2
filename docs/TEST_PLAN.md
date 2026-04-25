# BuildControl — Test Plan

A complete, end-to-end checklist for the test agent. Each test names the
**Steps**, the **Expected** result, and **How to verify** (Bitrix UI calls,
log lines, or HTTP responses). Where a test depends on prior data, the
prerequisite is called out.

The system under test is the production VPS:

- API: `http://162.120.19.127:8000`
- Public HTTPS via Cloudflare tunnel (URL changes on every restart — get the
  current one with `ssh root@162.120.19.127 "journalctl -u cloudflared -n 50 --no-pager | grep trycloudflare"`).
- Logs: `ssh root@162.120.19.127 "journalctl -u buildcontrol -n 200 --no-pager"`.
- Bitrix domain: see `BITRIX24_DOMAIN` in `/opt/buildcontrol/.env`.

---

## 1. System overview

BuildControl tracks plan-vs-actual on construction sites with anti-fraud controls.

```
Excel v3                → ExcelImporter → Bitrix workgroup + 5 universal lists + CRM tasks
Foreman daily report    → /api/report   → fact rows + cascade (task → phase → budget)
Buyer purchase request  → /api/purchase-request → list row + audit task + approver notification
Approver decision       → /api/purchase-requests/{id}/decide  (widget)
                          /approval/{id}/decide               (external page)
                          Telegram inline buttons
                            └─→ resolve_request()
                                  ├─ updates list status / history / comment
                                  ├─ if approve: applies materials math
                                  ├─ if approve OR reject: completes audit task
                                  └─ posts Telegram ack
```

Five universal lists per project:

| # | Sheet | Russian name | Purpose |
|---|-------|--------------|---------|
| 1 | Бюджет | "1. Бюджет" | Per-phase rollup |
| 2 | Этапы и задачи | "2. Этапы и задачи" | Per-task targets, link to CRM task |
| 3 | Материалы | "3. Материалы" | Per-line material plan + actual |
| 4 | Трудозатраты | "4. Трудозатраты" | Per-role labor plan + actual |
| 5 | Техника | "5. Техника" | Per-equipment plan + actual |

---

## 2. Environment setup

Before testing:

1. SSH to VPS, confirm service: `systemctl status buildcontrol --no-pager`.
2. `curl http://162.120.19.127:8000/health` → `{"status":"ok",...}`.
3. Open Bitrix24 → install / find the BuildControl widget (LEFT_MENU icon).
4. Have ready: `template_data/plan_fact_v3.xlsx`, a small valid PDF
   (≤ `MAX_PROPOSAL_FILE_MB`), a Bitrix user account that can see workgroups.

---

## 3. Excel import

| # | Steps | Expected | How to verify |
|---|-------|----------|---------------|
| 3.1 | In widget → "Импорт Excel" tab → upload `plan_fact_v3.xlsx`, optional project name. | All 5 progress steps light green. New workgroup appears in Bitrix. | Bitrix → "Группы и проекты" → see workgroup. Open it → 5 lists exist with the expected NAME columns (Этап, Задача, Наименование, Специальность, Техника). |
| 3.2 | Re-upload the SAME file with the SAME project name. | Either error "проект уже существует" or new project — must not silently overwrite. | Compare Bitrix workgroup count before/after. Check `journalctl -u buildcontrol` for warnings. |
| 3.3 | Upload a corrupted .xlsx (rename a `.txt` to `.xlsx`). | HTTP 400 with error message in widget. | Status text in widget; logs show "Failed to parse Excel". |
| 3.4 | Upload a valid v3 file with one **empty Этап name** in sheet "2. Этапы и задачи". | Import succeeds; empty rows are skipped. | List "2. Этапы и задачи" must not have a row with empty NAME. |
| 3.5 | Upload a file with > 10 phases. | All phases imported into "1. Бюджет"; no rate-limit failures. | Count of "1. Бюджет" rows == phase count. No `QUERY_LIMIT_EXCEEDED` errors after retries. |

---

## 4. Foreman daily report

| # | Steps | Expected | How to verify |
|---|-------|----------|---------------|
| 4.1 | Widget → "Отчет прораба" → pick project, pick task, fill in 1 material qty, submit. | "Отчёт сохранён" + cascade triggered. | List "3. Материалы" → row's "Объём израсходовано" increased by qty, "Остаток на складе" decreased. List "2. Этапы и задачи" → "Бюджет факт" rolls up. List "1. Бюджет" → phase "Материалы факт" rolls up. |
| 4.2 | Multi-task report: add a second task block, fill labor + equipment hours. | Both blocks saved; cascade runs for both tasks. | All affected rows updated; logs show one `cascade_update_task` call per task. |
| 4.3 | Comment-only report (no qty changes) with kanban move to a "PROGRESS" stage. | List is untouched; CRM task moved to chosen stage; comment posted to task chat; "Дата нач. факт" set. | In Bitrix open the task → Kanban shows new stage; chat shows comment. List "2. Этапы и задачи" → "Дата нач. факт" populated. |
| 4.4 | Submit report with kanban move to the **last** stage (FINISH). | Task `tasks.task.complete` called; "Дата ок. факт" set. | Bitrix task state = "Завершена"; list cell "Дата ок. факт" populated only on first FINISH move. |
| 4.5 | Submit a report twice with the same data. | Both succeed (no idempotency contract); "Объём израсходовано" doubles. | Confirm in list. Document this for the user — current behaviour is additive. |
| 4.6 | Submit with `qty > Объём план - Объём израсходовано`. | Saved (no server-side block), but inventory may go negative. | "Остаток на складе" goes negative. Check whether that is acceptable for the workflow. |

---

## 5. Cascade

| # | Steps | Expected | How to verify |
|---|-------|----------|---------------|
| 5.1 | After a foreman report on task A in phase X: read "Бюджет факт" on task A row in "2. Этапы и задачи". | Equals SUM(Стоим. факт) on materials in task A + SUM(ФОТ факт) + SUM(Итого факт on equipment). | Manually sum from list 3/4/5 and compare. |
| 5.2 | After cascade on task A: read "1. Бюджет" row for phase X. | "Материалы факт" / "ФОТ факт" / "Техника факт" / "Итого факт" all equal sums of corresponding columns across all tasks of phase X. | Manually sum and compare. |
| 5.3 | Run cascade after a buyer **approval** (not a foreman report). | Materials math updates "Объём куплено" + weighted "Цена ед. факт"; cascade is **not** triggered automatically because no "Стоим. факт" changes. | Verify only "Объём куплено", "Остаток", "Цена ед. факт" change after approval. |

---

## 6. Buyer purchase request — `/api/purchase-request`

| # | Steps | Expected | How to verify |
|---|-------|----------|---------------|
| 6.1 | Widget → "Заявка на закупку" → pick project, add 1 material with `cost = qty × price_plan`, attach valid PDF, submit. | Success: green block "Заявка №N отправлена на согласование." (no link). | List "Заявки на закупку" has new row with status "Ожидает". Audit task created in Bitrix CRM (visible in workgroup tasks). Telegram message arrives in approver chat. |
| 6.2 | Submit with **no PDF**. | HTTP 400 with message "Приложите счёт или коммерческое предложение (PDF)." | Front-end blocks before request sent; if posted via curl → server returns 400 from FastAPI `File(...)` requirement. |
| 6.3 | Submit a non-PDF (e.g. `.jpg`). | HTTP 415 "Допускаются только PDF-файлы". | `curl -F proposal=@x.jpg ...` |
| 6.4 | Submit PDF > `MAX_PROPOSAL_FILE_MB`. | HTTP 413 "File exceeds limit of N MB". | `curl -F proposal=@big.pdf ...` |
| 6.5 | Submit with `cost = qty × price_plan × 1.5` (50% over) and **no comment**. | HTTP 400 "Комментарий обязателен: цена превышает план для позиций: ...". Front-end blocks too. | `curl -X POST -F project_id=... -F items_json='[{"material_name":"X","qty":1,"price":150,"price_plan":100}]' -F proposal=@a.pdf` |
| 6.6 | Same as 6.5 but include `buyer_comment="Дефицит на рынке, других предложений нет"`. | 200 OK; row created. | Check list row → "Комментарий" field starts with `[Закупщик] ...`. |
| 6.7 | Submit price ≤ price_plan. | 200 OK without comment requirement. | Confirm. |
| 6.8 | Submit with empty `items_json` array. | HTTP 400 "items_json must be a non-empty array". | curl. |
| 6.9 | Confirm front-end DOES NOT show an approval link on success. | Success block contains only "Заявка №N отправлена на согласование." — no `<a>` tag. | Inspect the success div's innerHTML in browser devtools. |

---

## 7. Approver flow — Bitrix widget tab

| # | Steps | Expected | How to verify |
|---|-------|----------|---------------|
| 7.1 | Open widget → "Согласование" tab. | List of pending requests across all projects, sorted by date desc. | Must match the rows in every project's "Заявки на закупку" with status "Ожидает". |
| 7.2 | Click a request card. | Detail panel renders: items table, attached PDF link, buyer comment (if any), graded severity banners (if price > plan), comment textarea, three buttons. | Visual check. |
| 7.3 | Submit a request priced **+1%** vs plan → open it in approval tab. | Banner: 🟡 yellow, no header, body "Цена превышает план на 1.0%. Перерасход составит N ₽ ...". | Visual check + curl `GET /api/purchase-requests/{id}` → `items[0].severity.severity == "low"`. |
| 7.4 | Same with **+3%**. | 🟠 + header "ОБРАТИТЕ ВНИМАНИЕ". | severity == "medium". |
| 7.5 | Same with **+7%**. | 🔴 + header "ВНИМАНИЕ". | severity == "high". |
| 7.6 | Same with **+50%**. | 🚨 + header "КРИТИЧЕСКОЕ ПРЕВЫШЕНИЕ ПЛАНА". | severity == "critical". |
| 7.7 | Same with **price ≤ plan**. | ✅ banner "Цена в рамках плана (план X, факт Y)" or no banner at all if severity is "ok". | severity == "ok". |
| 7.8 | Click ✅ Подтвердить on a pending request. | Status flips to "Подтверждено"; Telegram ack arrives; **Bitrix audit task is closed**; "3. Материалы" updated (Объём куплено / Цена ед. факт weighted). | `tasks.task.get { taskId }` → `STATUS == 5` (closed). Materials list updated. Pending list refreshes and the request is gone. |
| 7.9 | Click ❌ Отклонить on another pending request. | Status "Отклонено"; **audit task closed**; **materials NOT updated**. Telegram ack with ❌. | Same as 7.8 but verify "3. Материалы" rows for this request's materials are unchanged. |
| 7.10 | Click 💬 Только комментарий with text in textarea. | Status remains "Ожидает"; **audit task remains open**; comment appended to list row's "Комментарий". | List row visible → "Комментарий" suffix `[Согласующий] <text>`; task still in active stage. |
| 7.11 | Idempotent: re-approve an already-approved request via curl. | Server returns `{"already_resolved": true, "status": "Подтверждено"}` (no double-apply). | `curl -X POST /api/purchase-requests/{id}/decide -F decision=approve` twice. |
| 7.12 | Approve a request whose audit task was manually closed in Bitrix. | No error; task-complete call swallowed by `complete_task`'s "already" guard. | `journalctl` shows no warning, no traceback. |

---

## 8. Approver flow — external page (backwards compat)

| # | Steps | Expected | How to verify |
|---|-------|----------|---------------|
| 8.1 | In Telegram, click "📝 Открыть форму". | Browser opens `/approval/{id}?token=...`. Page renders items, severity banner (using same graded helper), buyer comment, three decision buttons + comment textarea. **No actor-name input. No history card.** | Visual check. |
| 8.2 | Click ✅ → page refreshes, shows green status badge "Подтверждено". | Audit task closed; materials updated; Telegram ack. | Same checks as 7.8. |
| 8.3 | Tamper with `?token=...`. | HTTP 403 "Invalid or missing token". | curl. |
| 8.4 | Open the page for an already-resolved request. | "Заявка уже обработана: <status>" banner; no decision form. | Visual check. |

---

## 9. Approver flow — Telegram inline buttons

| # | Steps | Expected | How to verify |
|---|-------|----------|---------------|
| 9.1 | Telegram → click ✅ Подтвердить on a pending request. | Bot edits the message to show resolution; same downstream effects as 7.8. | Same checks as 7.8. |
| 9.2 | Telegram → click ❌ Отклонить. | Same as 7.9. | Same checks. |
| 9.3 | Telegram → click 💬 Написать → send a comment in reply. | Status unchanged; comment appended to list row. | Same as 7.10. |

---

## 10. Bitrix list-field integrity

After every approve/reject:

- `f_pr_status` ∈ {"Подтверждено", "Отклонено"}.
- `f_pr_history` is valid JSON; last entry has correct `event`, `actor`, `source`, `ts`.
- `f_pr_comment` retains buyer comment + every approver comment (each line prefixed `[actor]`).
- `f_pr_btask_id` matches a real Bitrix task that is now in status 5 (closed).

Run: `curl -s "http://162.120.19.127:8000/api/purchase-requests/{id}"` → cross-check.

---

## 11. Regression checklist (must still work after this release)

- [ ] Excel import end-to-end (3.1).
- [ ] Foreman daily report writes to lists 3/4/5 (4.1, 4.2).
- [ ] Cascade rolls up correctly (5.1, 5.2).
- [ ] Kanban move from foreman report still triggers `task.stages.movetask` (4.3, 4.4).
- [ ] Telegram approver buttons still work (9.x).
- [ ] External `/approval/{id}` page still works for backwards compat (8.x).

---

## 12. Known limitations

- **Hardcoded `user_id = 1`**: All buyer/approver actions are attributed to user_id 1 / display names "Закупщик" and "Согласующий". The real Bitrix user is not yet used. Production deploy must wire `BX24.callMethod('user.current')` and pass the real ID.
- **Concurrency**: ≥ 10 concurrent report/approval POSTs may exhaust the 5-retry budget on `QUERY_LIMIT_EXCEEDED` and surface as HTTP 500. Not a real problem at expected single-user-per-form load.
- **Foreman report idempotency**: re-submitting the same form **adds** to facts (4.5). No dedupe.
- **Rate limit**: Bitrix24 webhook is 2 req/sec → 0.5s minimum between calls (`bitrix/client.py`).
- **Cloudflare tunnel URL** is volatile — if Telegram links stop working, the tunnel restarted; refresh `VPS_URL` env and `systemctl restart buildcontrol`.
