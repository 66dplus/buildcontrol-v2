"""
Live integration test runner for the BuildControl AI agent.

Runs 18 real queries (Russian, free-form) against run_agent() with the actual
OpenRouter LLM + real SQLite DB.  Write-tool tests are guarded by SKIP_WRITES.

Usage:
    python scripts/test_agent_live.py              # all tests, skip writes
    python scripts/test_agent_live.py --writes     # include write tests
    python scripts/test_agent_live.py --ids 1,5,9  # run specific test IDs only
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root on sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.agent.core import run_agent  # noqa: E402 — needs sys.path patch above
from config import settings  # noqa: E402


# ── colour helpers ────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"


def _c(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET


# ── test definitions ──────────────────────────────────────────────────────────

# Each test: (id, category, query, expected_signals, is_write)
# expected_signals: list of strings that SHOULD appear in the final text reply
#                   OR tool names that MUST be called.
# Prefix a signal with "tool:" to require a specific tool call.
# Prefix with "!tool:" to require the tool NOT to be called.

TESTS: list[tuple[int, str, str, list[str], bool]] = [
    # ── READ: list / basics ────────────────────────────────────────────────
    (1,  "read",  "Какие у меня проекты?",
     ["tool:list_projects", "ТЦ Северный"],
     False),

    (2,  "read",  "Покажи все активные проекты с их ID",
     ["tool:list_projects", "1001", "1002", "1003"],
     False),

    # ── READ: budget ───────────────────────────────────────────────────────
    (3,  "read",  "Бюджет по ТЦ Северный — план vs факт по этапам",
     ["tool:query_database", "Каркас"],
     False),

    (4,  "read",  "По каким этапам есть перерасход бюджета?",
     ["tool:query_database", "перерасход"],
     False),

    (5,  "read",  "Какой план по ФОТ на Логистическом центре Восток?",
     ["tool:query_database"],
     False),

    # ── READ: tasks ────────────────────────────────────────────────────────
    (6,  "read",  "Какие задачи просрочены по всем проектам?",
     ["tool:query_database"],
     False),

    (7,  "read",  "Что сейчас в работе по ТЦ Меридиан?",
     ["tool:query_database"],
     False),

    (8,  "read",  "Сколько выполнено по этапу Фундамент в ТЦ Меридиан?",
     ["tool:query_database", "Фундамент"],
     False),

    (9,  "read",  "Покажи топ-3 задачи с наименьшим процентом выполнения",
     ["tool:query_database"],
     False),

    (10, "read",  "Какие задачи планируются на ближайшие 30 дней?",
     ["tool:query_database"],
     False),

    # ── READ: materials ────────────────────────────────────────────────────
    (11, "read",  "Сколько бетона израсходовано на ТЦ Северный?",
     ["tool:query_database"],
     False),

    (12, "read",  "Остатки материалов на складе по ТЦ Северный",
     ["tool:query_database"],
     False),

    (13, "read",  "Есть ли перерасход по материалам в Жилом комплексе Заречье?",
     ["tool:query_database"],
     False),

    # ── READ: purchase requests ────────────────────────────────────────────
    (14, "read",  "Какие заявки ждут согласования?",
     ["tool:query_database"],
     False),

    # ── READ: aggregate / comparison ──────────────────────────────────────
    (15, "read",  "Сравни бюджет факт и план по всем проектам — есть ли серьёзные отклонения?",
     ["tool:query_database"],
     False),

    # ── EDGE: off-topic / greeting ─────────────────────────────────────────
    (16, "edge",  "Привет, как дела?",
     [],   # any polite reply is fine
     False),

    (17, "edge",  "Что такое BuildControl?",
     [],
     False),

    # ── WRITE (skipped by default) ─────────────────────────────────────────
    (18, "write", "Создай задачу 'Тест: проверка агента 2026-05-10' в проекте ТЦ Северный (ID=1)",
     ["tool:create_task", "создана"],
     True),
]


# ── runner ────────────────────────────────────────────────────────────────────

async def run_test(
    test_id: int,
    category: str,
    query: str,
    signals: list[str],
    is_write: bool,
    skip_writes: bool,
) -> dict[str, Any]:
    if is_write and skip_writes:
        return {"id": test_id, "status": "skipped", "query": query}

    session = f"live-test-{test_id}"
    events: list[dict] = []
    tools_called: list[str] = []
    text_parts: list[str] = []
    errors: list[str] = []

    t0 = time.monotonic()
    try:
        async for ev in run_agent(query, project_id=None, session_id=session):
            events.append(ev)
            etype = ev.get("type", "")
            if etype == "text":
                text_parts.append(ev.get("content", ""))
            elif etype == "tool_call":
                tools_called.append(ev.get("name", ""))
            elif etype == "error":
                errors.append(ev.get("content", ""))
    except Exception as exc:
        errors.append(f"EXCEPTION: {exc}")

    elapsed = time.monotonic() - t0
    full_text = "".join(text_parts).strip()

    # Check signals
    failed_signals: list[str] = []
    for sig in signals:
        if sig.startswith("tool:"):
            tool_name = sig[5:]
            if tool_name not in tools_called:
                failed_signals.append(f"expected tool call '{tool_name}' — not called (called: {tools_called})")
        elif sig.startswith("!tool:"):
            tool_name = sig[6:]
            if tool_name in tools_called:
                failed_signals.append(f"tool '{tool_name}' should NOT be called — was called")
        else:
            if sig.lower() not in full_text.lower():
                failed_signals.append(f"expected '{sig}' in reply")

    status = "pass" if not failed_signals and not errors else "fail"
    return {
        "id": test_id,
        "status": status,
        "category": category,
        "query": query,
        "tools_called": tools_called,
        "reply": full_text,
        "errors": errors,
        "failed_signals": failed_signals,
        "elapsed": elapsed,
        "events": events,
    }


def _print_result(r: dict) -> None:
    status = r["status"]
    icon = {"pass": "✓", "fail": "✗", "skipped": "–"}[status]
    colour = {"pass": GREEN, "fail": RED, "skipped": DIM}[status]

    print(_c(f"\n[{r['id']:02d}] {icon} {r['query']}", BOLD, colour))

    if status == "skipped":
        print(_c("     skipped (write test, use --writes to enable)", DIM))
        return

    print(_c(f"     category={r['category']}  elapsed={r['elapsed']:.1f}s", DIM))

    if r["tools_called"]:
        print(_c(f"     tools → {', '.join(r['tools_called'])}", CYAN))

    # Trim reply for display
    reply = r["reply"]
    if len(reply) > 400:
        reply = reply[:397] + "…"
    if reply:
        for line in reply.splitlines()[:6]:
            print(_c(f"     {line}", ""))

    if r["errors"]:
        for e in r["errors"]:
            print(_c(f"     ERROR: {e}", RED))

    if r["failed_signals"]:
        for fs in r["failed_signals"]:
            print(_c(f"     SIGNAL FAIL: {fs}", YELLOW))


async def main(test_ids: list[int] | None, skip_writes: bool) -> None:
    if not settings.openrouter_api_key:
        print(_c("ERROR: OPENROUTER_API_KEY not set in .env — cannot run live tests.", RED, BOLD))
        sys.exit(1)

    print(_c(f"\nBuildControl Agent — Live Integration Tests", BOLD))
    print(f"Model  : {settings.openrouter_model}")
    print(f"DB     : {settings.db_path}")
    print(f"Writes : {'enabled' if not skip_writes else 'skipped (use --writes to enable)'}")
    print(_c("─" * 60, DIM))

    tests_to_run = TESTS
    if test_ids:
        tests_to_run = [t for t in TESTS if t[0] in test_ids]

    results = []
    for test_id, category, query, signals, is_write in tests_to_run:
        print(_c(f"Running [{test_id:02d}] {query[:60]}…", DIM), end="", flush=True)
        r = await run_test(test_id, category, query, signals, is_write, skip_writes)
        _print_result(r)
        results.append(r)

    # Summary
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    total_time = sum(r.get("elapsed", 0) for r in results if r["status"] != "skipped")

    print(_c("\n" + "─" * 60, DIM))
    print(_c(f"Results: {passed} passed, {failed} failed, {skipped} skipped", BOLD))
    print(f"Total time (non-skipped): {total_time:.1f}s\n")

    if failed:
        print(_c("Failed tests:", BOLD, RED))
        for r in results:
            if r["status"] == "fail":
                print(_c(f"  [{r['id']:02d}] {r['query']}", RED))
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--writes", action="store_true", help="Enable write-tool tests")
    parser.add_argument("--ids", help="Comma-separated test IDs to run, e.g. 1,3,7")
    args = parser.parse_args()

    ids = [int(x) for x in args.ids.split(",")] if args.ids else None
    asyncio.run(main(ids, skip_writes=not args.writes))
