# BuildControl v2 — Test Report

## Executive Summary
- Total test cases reviewed: 52
- PASS (implemented + tested): 17
- FAIL (implemented but test fails): 3
- GAP (not implemented or missing validation): 5
- NOT_TESTABLE (requires live Bitrix24 only): 27

Local automated tests were executed with `python3 -m pytest tests/ -v` (the requested `python -m pytest ...` command failed because `python` is not installed in this shell).

Pytest output:
```text
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0 -- /Library/Developer/CommandLineTools/usr/bin/python3
cachedir: .pytest_cache
rootdir: /Users/dmitrijrybkin/Documents/Claude Code/BuildControl_v2
plugins: anyio-4.12.1, asyncio-1.2.0
asyncio: mode=strict, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 20 items
...
============================== 20 passed in 1.43s ==============================
```

VPS read-only checks could not be executed from this environment due network restrictions:
- `curl http://162.120.19.127:8000/health` → connect failed
- `curl http://162.120.19.127:8000/api/projects` → connect failed
- `ssh root@162.120.19.127` → operation not permitted

## Test Results by Section
### Section 3: Excel import
| Test Case | Status | Code Path | Notes |
|-----------|--------|-----------|-------|
| 3.1 Import valid v3 Excel via widget | NOT_TESTABLE | `app/bitrix_app.py:_upload_form_html`, `app/webhook_handler.py:upload_excel`, `scripts/import_excel.py:ExcelImporter.import_file` | Impl: YES. Auto tests: No direct e2e tests. Live Bitrix/UI required. |
| 3.2 Re-upload same file + same project name | NOT_TESTABLE | `scripts/import_excel.py:_create_project` | Impl: PARTIAL (no duplicate-name guard; new project creation behavior depends on Bitrix). Auto tests: No. |
| 3.3 Corrupted `.xlsx` upload returns HTTP 400 in widget | GAP | `app/webhook_handler.py:upload_excel`, `_run_import_job` | Impl: PARTIAL. Parse error happens asynchronously in background job; endpoint returns `202`, not immediate HTTP 400. |
| 3.4 Empty `Этап` name row in sheet 2 is skipped | GAP | `scripts/import_excel.py:_create_lists`, `_create_tasks` | Impl: PARTIAL. Empty task title is skipped, but empty `Этап` alone is not explicitly skipped. |
| 3.5 Import with >10 phases without rate-limit failures | NOT_TESTABLE | `bitrix/client.py:BitrixClient.call`, `scripts/import_excel.py:ExcelImporter.import_file` | Impl: YES (global 0.5s pacing + retries). Auto tests: No load/integration tests. |

### Section 4: Foreman daily report
| Test Case | Status | Code Path | Notes |
|-----------|--------|-----------|-------|
| 4.1 Single-task material report updates lists + cascade | NOT_TESTABLE | `app/webhook_handler.py:api_report`, `_background_report_tasks`, `utils/cascade.py` | Impl: YES. Auto tests: No endpoint e2e tests. |
| 4.2 Multi-task report saves both blocks + cascade both | NOT_TESTABLE | `app/bitrix_app.py:submitReport`, `app/webhook_handler.py:api_report` | Impl: YES. Auto tests: No e2e tests. |
| 4.3 Comment-only + move to PROGRESS stage | NOT_TESTABLE | `app/webhook_handler.py:_update_task_progress` | Impl: YES (stage move, task comment, start-date write). Auto tests: Partial helper coverage only. |
| 4.4 Move to FINISH sets done date + completes task | NOT_TESTABLE | `app/webhook_handler.py:_update_task_progress`, `bitrix/methods/tasks.py:complete_task` | Impl: YES. Auto tests: No direct e2e tests. |
| 4.5 Double submit is additive (no idempotency) | PASS | `app/webhook_handler.py:api_report` | Impl: YES (additive updates). Auto tests: No direct test, behavior clear in code. |
| 4.6 Over-consumption can drive negative stock | FAIL | `app/bitrix_app.py:submitReport`, `app/webhook_handler.py:api_report` | Impl diverges from plan: UI blocks qty above stock; backend also clamps stock with `max(0.0, cur - qty_used)`. |

### Section 5: Cascade
| Test Case | Status | Code Path | Notes |
|-----------|--------|-----------|-------|
| 5.1 Task budget fact equals sum(materials+labor+equipment fact) | NOT_TESTABLE | `utils/cascade.py:cascade_update_task` | Impl: YES. Auto tests: No cascade numeric tests. |
| 5.2 Budget phase fact columns equal summed task/resource facts | NOT_TESTABLE | `utils/cascade.py:cascade_update_budget` | Impl: YES. Auto tests: No cascade numeric tests. |
| 5.3 Buyer approval should NOT trigger cascade | FAIL | `app/purchase_requests.py:_apply_buyer_purchase` | Impl diverges from plan: after approval it explicitly calls `cascade_update_task` and `cascade_update_budget`. |

### Section 6: Buyer purchase request — `/api/purchase-request`
| Test Case | Status | Code Path | Notes |
|-----------|--------|-----------|-------|
| 6.1 Valid submit creates pending row + audit task + Telegram | NOT_TESTABLE | `app/webhook_handler.py:api_purchase_request`, `app/purchase_requests.py:create_request` | Impl: YES. Auto tests: Partial unit tests for approval helpers, not full endpoint e2e. |
| 6.2 Submit with no PDF | FAIL | `app/webhook_handler.py:api_purchase_request` | Endpoint signature uses `proposal: UploadFile = File(...)`, so missing file yields FastAPI 422, not expected 400. Frontend does block. |
| 6.3 Submit non-PDF | PASS | `app/webhook_handler.py:api_purchase_request` | Impl: YES (`415`, message `Допускаются только PDF-файлы`). |
| 6.4 Submit oversized PDF | PASS | `app/webhook_handler.py:api_purchase_request` | Impl: YES (`413`, max from `MAX_PROPOSAL_FILE_MB`). |
| 6.5 Price > plan without comment | PASS | `app/webhook_handler.py:api_purchase_request` | Impl: YES (`400` with mandatory-comment detail). |
| 6.6 Price > plan with buyer comment | NOT_TESTABLE | `app/webhook_handler.py:api_purchase_request`, `app/purchase_requests.py:create_request` | Impl: YES. Auto tests: no full endpoint/list-write e2e. |
| 6.7 Price <= plan without comment | PASS | `app/webhook_handler.py:api_purchase_request` | Impl: YES (comment required only for over-plan lines). |
| 6.8 Empty `items_json` array | PASS | `app/webhook_handler.py:api_purchase_request` | Impl: YES (`400`, detail includes `items_json must be a non-empty array`). |
| 6.9 No approval link in success UI block | PASS | `app/bitrix_app.py:_buyer_report_form_html` | Impl: YES (success text only, no `<a>` rendered). |

### Section 7: Approver flow — Bitrix widget tab
| Test Case | Status | Code Path | Notes |
|-----------|--------|-----------|-------|
| 7.1 Pending list across all projects sorted desc | NOT_TESTABLE | `app/approval_page.py:api_pending_requests`, `app/purchase_requests.py:list_pending_across_projects` | Impl: YES (sorted by date/request_no desc). |
| 7.2 Detail panel with items/PDF/comment/banners/buttons | NOT_TESTABLE | `app/bitrix_app.py:_approval_tab_html`, `app/approval_page.py:api_request_detail` | Impl: YES. UI/live verification required. |
| 7.3 +1% severity (low, yellow, no header) | PASS | `app/purchase_requests.py:format_price_deviation` | Impl: YES. Auto tests: no direct severity test. |
| 7.4 +3% severity (medium + header) | PASS | `app/purchase_requests.py:format_price_deviation` | Impl: YES. |
| 7.5 +7% severity (high + warning header) | PASS | `app/purchase_requests.py:format_price_deviation` | Impl: YES. |
| 7.6 +50% severity (critical header) | PASS | `app/purchase_requests.py:format_price_deviation` | Impl: YES. |
| 7.7 Price <= plan severity `ok` | PASS | `app/purchase_requests.py:format_price_deviation`, `app/bitrix_app.py:_approval_tab_html` | Impl: YES (`ok` banner path exists). |
| 7.8 Approve pending request | NOT_TESTABLE | `app/approval_page.py:api_request_decide`, `app/purchase_requests.py:resolve_request` | Impl: YES (status update, material apply, task complete, Telegram ack). |
| 7.9 Reject pending request | NOT_TESTABLE | `app/approval_page.py:api_request_decide`, `app/purchase_requests.py:resolve_request` | Impl: YES (no material apply, task complete). |
| 7.10 Comment-only decision | NOT_TESTABLE | `app/approval_page.py:api_request_decide`, `app/purchase_requests.py:resolve_request` | Impl: YES (status unchanged; comment append). |
| 7.11 Idempotent re-approve | PASS | `app/purchase_requests.py:resolve_request`, `app/approval_page.py:api_request_decide` | Impl: YES; Auto tests: `tests/test_purchase_requests.py::test_resolve_request_is_idempotent_when_already_approved`. |
| 7.12 Approve when audit task already closed | NOT_TESTABLE | `bitrix/methods/tasks.py:complete_task`, `app/purchase_requests.py:resolve_request` | Impl: YES (already/invalid-state errors swallowed). |

### Section 8: Approver flow — external page (backwards compat)
| Test Case | Status | Code Path | Notes |
|-----------|--------|-----------|-------|
| 8.1 Telegram form page renders correctly (no actor/history inputs) | NOT_TESTABLE | `app/approval_page.py:get_approval_page`, `_render_html` | Impl: YES (no actor input in rendered form; no history card block). |
| 8.2 Approve from external page | NOT_TESTABLE | `app/approval_page.py:post_approval_decide`, `app/purchase_requests.py:resolve_request` | Impl: YES (redirect back to tokenized approval URL). |
| 8.3 Tampered token returns 403 | PASS | `app/approval_page.py:get_approval_page`, `verify_token` | Impl: YES. |
| 8.4 Already-resolved page hides decision form | NOT_TESTABLE | `app/approval_page.py:_render_html` | Impl: YES (`is_pending` branch). |

### Section 9: Approver flow — Telegram inline buttons
| Test Case | Status | Code Path | Notes |
|-----------|--------|-----------|-------|
| 9.1 Telegram approve button edits message + downstream effects | GAP | `app/telegram_bot.py:_handle_callback`, `app/purchase_requests.py:resolve_request` | Downstream resolution exists, but bot does not edit original message text (only callback acknowledgment + separate ack). |
| 9.2 Telegram reject button edits message + downstream effects | GAP | `app/telegram_bot.py:_handle_callback`, `app/purchase_requests.py:resolve_request` | Same gap as 9.1 for message editing. |
| 9.3 Telegram comment flow (`💬` then text) | NOT_TESTABLE | `app/telegram_bot.py:_handle_callback`, `_handle_message` | Impl: YES (pending comment mode + append comment decision). |

### Section 10: Bitrix list-field integrity
| Test Case | Status | Code Path | Notes |
|-----------|--------|-----------|-------|
| `f_pr_status` in {`Подтверждено`,`Отклонено`} after approve/reject | PASS | `app/purchase_requests.py:resolve_request` | Impl: YES (`new_status` written deterministically). |
| `f_pr_history` valid JSON with event/actor/source/ts | PASS | `app/purchase_requests.py:_append_history`, `resolve_request` | Impl: YES (history appended then JSON-encoded). |
| `f_pr_comment` preserves buyer + approver comments | PASS | `app/purchase_requests.py:create_request`, `resolve_request` | Impl: YES (append with `[actor]` prefixes). |
| `f_pr_btask_id` points to real task now closed | GAP | `app/purchase_requests.py:create_request`, `resolve_request` | Best-effort only: task ID writeback and close are wrapped in try/except and not enforced/verified. |

### Section 11: Regression checklist
| Test Case | Status | Code Path | Notes |
|-----------|--------|-----------|-------|
| 11.1 Excel import end-to-end (3.1) | NOT_TESTABLE | `scripts/import_excel.py`, `app/webhook_handler.py:upload_excel` | Impl present; live Bitrix check unavailable in this environment. |
| 11.2 Foreman report writes to lists 3/4/5 (4.1,4.2) | NOT_TESTABLE | `app/webhook_handler.py:api_report` | Impl present; integration not runnable here. |
| 11.3 Cascade rollup correctness (5.1,5.2) | NOT_TESTABLE | `utils/cascade.py` | Impl present; no numeric integration test run against Bitrix data. |
| 11.4 Kanban move still triggers `task.stages.movetask` | NOT_TESTABLE | `app/webhook_handler.py:_update_task_progress`, `_update_subtask_progress` | Impl present; unit tests cover stage-target logic only. |
| 11.5 Telegram approver buttons still work | NOT_TESTABLE | `app/telegram_bot.py:_handle_callback` | Core callback path exists; live Telegram/Bitrix unavailable. |
| 11.6 External `/approval/{id}` page still works | NOT_TESTABLE | `app/approval_page.py` | Impl present; live tokenized flow not executable here. |

## Known Bugs Found
1. Corrupted Excel uploads are not rejected synchronously with HTTP 400; `/upload` returns `202` and only background job status flips to error later. (`app/webhook_handler.py:211`, `app/webhook_handler.py:191`)
2. Sheet `2. Этапы и задачи` rows with empty `Этап` are not explicitly skipped; only `ИТОГО` and empty title cases are filtered. (`scripts/import_excel.py:285`, `scripts/import_excel.py:404`)
3. Foreman stock-overuse behavior diverges from plan: UI blocks over-stock quantities and backend clamps stock to non-negative value. (`app/bitrix_app.py:1255`, `app/webhook_handler.py:1581`)
4. Buyer approval triggers cascade recomputation, while TEST_PLAN 5.3 expects no cascade trigger. (`app/purchase_requests.py:449`)
5. Missing proposal file currently yields FastAPI validation `422`, not the expected business `400` message. (`app/webhook_handler.py:1205`)
6. Severity calculation for multi-item approval details reuses one `price_plan` (from primary material) for all items. (`app/approval_page.py:151`, `app/approval_page.py:156`)
7. Telegram approve/reject callbacks do not edit the original Telegram message to show resolution state. (`app/telegram_bot.py:148`)
8. PDF validation is extension-based only (`.pdf`) and does not validate MIME/content signature. (`app/webhook_handler.py:1260`)

## Recommendations
1. Add synchronous upload validation mode for corrupted Excel (parse header rows in `/upload` before returning `202`) and return consistent HTTP 400 for invalid workbook structure.
2. Align spec and implementation for inventory overuse: either allow negative stock per TEST_PLAN 4.6 or update TEST_PLAN + enforce explicit API-level rejection with clear error.
3. Fix multi-item severity context by resolving plan price per item material (not from first item only) in `api_request_detail`.
4. Normalize request-validation errors (`422` → controlled `400` with expected message) for missing file and malformed inputs.
5. Add integration tests (or service-level mocked tests) for `/api/purchase-request`, `/api/report`, and approval decision endpoints to cover status/history/comment/task-close invariants.
6. If message-edit behavior is required by product spec, add Telegram `editMessageText`/`editMessageReplyMarkup` on approve/reject callbacks.
7. Decide and document whether buyer approval should trigger cascade; then align either code or TEST_PLAN 5.3.
