"""
Manual QA runner for the director Telegram agent.

Runs a battery of questions against the live agent on the VPS (real SQLite DB +
OpenRouter), captures replies instead of sending to Telegram, runs sanity
checks against the real DB, and writes a structured log.

Usage (run on VPS):
    cd /opt/buildcontrol && venv/bin/python3 scripts/test_agent_qa.py
    cd /opt/buildcontrol && venv/bin/python3 scripts/test_agent_qa.py --extended

Exit code: 0 if all sanity checks pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import sys
import textwrap
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.notifications.telegram as tg_module
import app.telegram_agent as agent_module
from app.telegram_agent import handle_director_query
from config import settings

# ---------------------------------------------------------------------------
# Question battery
# ---------------------------------------------------------------------------

# (number, category, question, sanity_check_id)
# sanity_check_id is None or a key into SANITY_CHECKS below.
BASE_QUESTIONS: list[tuple[str, str, str, str | None]] = [
    ("1",  "Закупки",     "Что закупили для ЖК Питер?",                                  "has_materials_питер"),
    ("2",  "Закупки",     "Сколько топлива сейчас на складе в ЖК Питер?",                None),
    ("3",  "Закупки",     "По какому материалу на ЖК Питер израсходовано больше всего?", None),
    ("4",  "Закупки",     "Есть ли на ЖК Питер материалы, которые куплены, но ещё не израсходованы?", None),
    ("5",  "Бюджет",      "Как идёт бюджет на ЖК Питер?",                                "budget_питер_has_plan"),
    ("6",  "Бюджет",      "Есть ли перерасход на ЖК Питер?",                             None),
    ("7",  "Бюджет",      "Сколько потрачено на материалы по проекту ЖК Питер?",         None),
    ("8",  "Задачи",      "Какие задачи просрочены на ЖК Питер?",                        None),
    ("9",  "Задачи",      'Какой прогресс по этапу "Фундамент" на ЖК Питер?',            None),
    ("10", "Задачи",      "Какие задачи у нас запланированы на следующий месяц по ЖК Питер?", None),
    ("11", "ФОТ/Техника", "Сколько ч-часов списано по ЖК Питер?",                        None),
    ("12", "ФОТ/Техника", "Покажи расходы на технику по ЖК Питер",                       None),
    ("13", "Общий",       "Всё нормально на ЖК Питер?",                                  None),
    ("14", "Общий",       "Что нового по ЖК Питер за последнее время?",                  None),
    ("15", "Общий",       "Есть ли активные заявки на закупку по ЖК Питер?",             None),
]

EXTENDED_QUESTIONS: list[tuple[str, str, str, str | None]] = [
    ("E1",  "Edge:NoProj",   "Что закупили на проекте Несуществующий?",                                "says_not_found"),
    ("E2",  "Edge:Phase",    "Какой план бюджета на фундамент в ЖК Питер?",                            "budget_phase_фундамент"),
    ("E3",  "Edge:QtySem",   "Сколько арматуры куплено и сколько израсходовано на ЖК Питер?",          None),
    ("E4",  "Edge:Empty",    "Сколько потратили на благоустройство на ЖК Питер?",                      "no_zero_zero"),
    ("E5",  "Edge:Total",    "Сколько всего по плану и потрачено по ЖК Питер?",                        "budget_total_питер"),
    ("E6",  "Edge:Overspend", "Перерасход на этапе Земляные работы в ЖК Питер?",                       None),
    ("E7",  "Edge:Pending",  "Есть ли заявки на закупку, ждущие утверждения?",                         None),
    ("E8",  "Edge:Project2", "Что есть по проекту Березки?",                                           "mentions_березки"),
    ("E9",  "Edge:Format",   "Назови три самых дорогих этапа в ЖК Питер по плану.",                    "budget_phase_фундамент"),

    # ---- Multi-project comparisons ----
    ("M1",  "Multi:List",       "Какие проекты сейчас активны? Покажи списком.",                       "lists_both_projects"),
    ("M2",  "Multi:Compare",    "Сравни бюджет ЖК Питер и ИЖС Березки — где план больше?",             "mentions_both_projects"),
    ("M3",  "Multi:TotalAll",   "Какой суммарный план бюджета по всем активным проектам?",             "all_projects_total"),
    ("M4",  "Multi:OverdueAll", "На каких проектах есть просроченные задачи?",                         None),
    ("M5",  "Multi:Switch",     "А по ИЖС Березки сколько задач завершено и сколько в работе?",        "mentions_березки"),

    # ---- Date arithmetic ----
    ("D1",  "Date:Next7",       "Какие задачи начинаются на следующей неделе по ЖК Питер?",            None),
    ("D2",  "Date:Last30",      "Какие задачи стартовали за последние 30 дней по ЖК Питер?",           None),
    ("D3",  "Date:Done",        "Какие задачи уже завершены по ЖК Питер? Укажи дату завершения.",      None),
    ("D4",  "Date:Long",        "Какая задача самая длинная по плану в ЖК Питер? Сколько дней?",       None),
    ("D5",  "Date:DueSoon",     "Что должно закончиться в ближайшие 14 дней по ЖК Питер?",             None),

    # ---- JSON drilldown into purchase_requests.items_json ----
    ("J1",  "JSON:Items",       "Что было в последней одобренной заявке на закупку по ЖК Питер?",      "no_sql_error"),
    ("J2",  "JSON:Total",       "На какую сумму одобрено заявок на закупку по ЖК Питер?",              "no_sql_error"),
    ("J3",  "JSON:Rejected",    "Почему отклоняли заявки на закупку по ЖК Питер? Покажи комментарии.", "no_sql_error"),
    ("J4",  "JSON:Top",         "Какой материал чаще всего фигурирует в заявках на закупку?",          "no_sql_error"),
]

# ---------------------------------------------------------------------------
# Sanity checks: each takes the captured plain-text reply and a sqlite conn.
# Returns (ok: bool, reason: str).
# ---------------------------------------------------------------------------

def _питер_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT id FROM projects WHERE LOWER(name) LIKE '%итер%' LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def chk_has_materials_питер(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    pid = _питер_id(conn)
    n = conn.execute(
        "SELECT COUNT(*) FROM materials WHERE project_id=? AND qty_bought>0", (pid,)
    ).fetchone()[0]
    if n == 0:
        return True, "no purchases in DB; nothing to assert"
    if "не найден" in reply.lower() or "нет данных" in reply.lower():
        return False, f"DB has {n} bought materials but agent says nothing found"
    return True, f"agent mentioned purchases (DB has {n})"


def chk_budget_питер_has_plan(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    pid = _питер_id(conn)
    plan = conn.execute(
        """SELECT SUM(COALESCE(NULLIF(total_plan,0),
                              materials_plan+labor_plan+equipment_plan))
           FROM budget_phases WHERE project_id=?""",
        (pid,),
    ).fetchone()[0] or 0
    if plan == 0:
        return True, "no plan in DB; nothing to assert"
    if "из 0 ₽" in reply or "не заполнен" in reply.lower():
        return False, f"DB has plan={plan:.0f} but agent reports zero/empty"
    return True, f"agent acknowledged plan (DB plan={plan:.0f})"


def chk_says_not_found(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    rl = reply.lower()
    keywords = ["не найден", "не существует", "нет такого", "не нашёл", "не нашел", "отсутству"]
    if any(k in rl for k in keywords):
        return True, "correctly reported missing project"
    # Tolerate "нет данных" too
    if "нет данных" in rl:
        return True, "reported no data"
    return False, "did not clearly say project missing"


def chk_budget_phase_фундамент(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    pid = _питер_id(conn)
    row = conn.execute(
        """SELECT phase_name,
                  COALESCE(NULLIF(total_plan,0),
                           materials_plan+labor_plan+equipment_plan) AS plan_total
           FROM budget_phases
           WHERE project_id=? AND LOWER(phase_name) LIKE '%фундамент%'""",
        (pid,),
    ).fetchone()
    if not row:
        return True, "no foundation phase; skip"
    plan_total = row[1] or 0
    if plan_total == 0:
        return True, "phase has 0 plan; skip"
    # Reply must contain a number that's at least 6 digits (e.g. 1 940 000)
    digits = re.sub(r"\D", "", reply)
    if str(int(plan_total))[:3] not in digits and str(int(plan_total // 1000))[:3] not in digits:
        return False, f"foundation plan={plan_total:.0f} not in reply"
    return True, "foundation plan number present"


def chk_no_zero_zero(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    if "0 ₽ из 0 ₽" in reply or "0₽ из 0₽" in reply:
        return False, "still emits '0 ₽ из 0 ₽'"
    return True, "no '0 ₽ из 0 ₽' phrasing"


def chk_budget_total_питер(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    pid = _питер_id(conn)
    plan = conn.execute(
        """SELECT SUM(COALESCE(NULLIF(total_plan,0),
                              materials_plan+labor_plan+equipment_plan))
           FROM budget_phases WHERE project_id=?""",
        (pid,),
    ).fetchone()[0] or 0
    if plan < 1_000_000:
        return True, "no meaningful plan total; skip"
    digits = re.sub(r"\D", "", reply)
    # Total for ЖК Питер ~10M; expect "10" or first 2 digits of plan in millions
    millions = int(plan // 1_000_000)
    if str(millions) not in digits and str(millions - 1) not in digits and str(millions + 1) not in digits:
        return False, f"plan total ≈{millions} млн not present in reply"
    return True, f"plan total ≈{millions} млн present"


def chk_mentions_березки(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    rl = reply.lower()
    if "берёзк" in rl or "березк" in rl or "ижс" in rl:
        return True, "mentions Березки/ИЖС"
    return False, "no Березки/ИЖС mention"


def chk_lists_both_projects(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    rl = reply.lower()
    has_piter = "питер" in rl
    has_berez = ("берёзк" in rl) or ("березк" in rl) or ("ижс" in rl)
    if has_piter and has_berez:
        return True, "lists both ЖК Питер and ИЖС Березки"
    return False, f"missing project (piter={has_piter}, березки={has_berez})"


def chk_mentions_both_projects(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    return chk_lists_both_projects(reply, conn)


def chk_all_projects_total(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    total = conn.execute(
        """SELECT SUM(COALESCE(NULLIF(total_plan,0),
                              materials_plan+labor_plan+equipment_plan))
           FROM budget_phases bp
           JOIN projects p ON p.id = bp.project_id
           WHERE p.is_archived=0"""
    ).fetchone()[0] or 0
    if total < 1_000_000:
        return True, "skip — no meaningful total"
    digits = re.sub(r"\D", "", reply)
    millions = int(total // 1_000_000)
    for guess in (millions, millions - 1, millions + 1):
        if str(guess) in digits:
            return True, f"total ≈{millions} млн present"
    return False, f"global total ≈{millions} млн not in reply"


def chk_no_sql_error(reply: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    rl = reply.lower()
    bad = ["произошла ошибка", "ошибка при", "sql", "traceback", "exception"]
    if any(b in rl for b in bad):
        return False, "agent reply contains error wording"
    return True, "no error wording"


SANITY_CHECKS: dict[str, Callable[[str, sqlite3.Connection], tuple[bool, str]]] = {
    "has_materials_питер":     chk_has_materials_питер,
    "budget_питер_has_plan":   chk_budget_питер_has_plan,
    "says_not_found":          chk_says_not_found,
    "budget_phase_фундамент":  chk_budget_phase_фундамент,
    "no_zero_zero":            chk_no_zero_zero,
    "budget_total_питер":      chk_budget_total_питер,
    "mentions_березки":        chk_mentions_березки,
    "lists_both_projects":     chk_lists_both_projects,
    "mentions_both_projects":  chk_mentions_both_projects,
    "all_projects_total":      chk_all_projects_total,
    "no_sql_error":            chk_no_sql_error,
}

# ---------------------------------------------------------------------------
# Capture replies without sending to Telegram
# ---------------------------------------------------------------------------

captured_reply: str = ""


async def _fake_send_telegram(message: str, parse_mode: str = "HTML", chat_id: str | None = None) -> bool:
    global captured_reply
    captured_reply = message
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

DIVIDER = "─" * 70


async def run_qa(extended: bool, log_path: Path) -> int:
    tg_module.send_telegram = _fake_send_telegram  # type: ignore[assignment]
    agent_module.send_telegram = _fake_send_telegram  # type: ignore[assignment]

    questions = list(BASE_QUESTIONS)
    if extended:
        questions += EXTENDED_QUESTIONS

    db_conn = sqlite3.connect(settings.db_path)
    db_conn.row_factory = sqlite3.Row

    failures: list[str] = []
    log_lines: list[str] = []

    header = f"\n{'═' * 70}\n  BuildControl Director Agent — QA Test Run ({'extended' if extended else 'base'})\n{'═' * 70}\n"
    print(header)
    log_lines.append(header)

    for num, category, question, check_id in questions:
        global captured_reply
        captured_reply = ""

        line = f"[{num:>3}] [{category}]  {question}"
        print(line); log_lines.append(line); log_lines.append(DIVIDER)
        print(DIVIDER)

        try:
            await handle_director_query(chat_id=0, text=question)
        except Exception as exc:
            captured_reply = f"ERROR: {exc}"

        plain = re.sub(r"<[^>]+>", "", captured_reply)
        wrapped = textwrap.fill(plain, width=70, subsequent_indent="      ")
        print(f"  ➤ {wrapped}\n")
        log_lines.append(f"  REPLY: {plain}")

        if check_id:
            check = SANITY_CHECKS.get(check_id)
            if check:
                ok, reason = check(plain, db_conn)
                tag = "PASS" if ok else "FAIL"
                line = f"  CHECK [{check_id}] {tag}: {reason}"
                print(f"     {line.strip()}\n")
                log_lines.append(line)
                if not ok:
                    failures.append(f"[{num}] {question} — {reason}")

    summary = f"\n{'═' * 70}\n  Failures: {len(failures)}\n{'═' * 70}\n"
    for f in failures:
        summary += f"  ✗ {f}\n"
    print(summary)
    log_lines.append(summary)

    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"  Log: {log_path}\n")

    return 0 if not failures else 1


async def run_stress(extended: bool, iterations: int, log_dir: Path) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    total_fail = 0
    summary: list[str] = []
    for i in range(1, iterations + 1):
        log_path = log_dir / f"iter_{i:02d}.log"
        print(f"\n████ STRESS ITERATION {i}/{iterations} ████")
        rc = await run_qa(extended, log_path)
        verdict = "CLEAN" if rc == 0 else "FAILED"
        summary.append(f"  iter {i:02d}: {verdict}  ({log_path})")
        if rc != 0:
            total_fail += 1
    final = f"\n══ STRESS SUMMARY ══\n" + "\n".join(summary) + f"\n  Failed iterations: {total_fail}/{iterations}\n"
    print(final)
    (log_dir / "summary.txt").write_text(final, encoding="utf-8")
    return 0 if total_fail == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extended", action="store_true", help="include edge-case questions")
    parser.add_argument("--stress", type=int, default=0, metavar="N",
                        help="run the suite N times for nondeterminism stress test")
    parser.add_argument("--log", type=Path, default=Path(f"/tmp/agent_qa_{int(time.time())}.log"))
    parser.add_argument("--log-dir", type=Path, default=Path(f"/tmp/agent_qa_stress_{int(time.time())}"))
    args = parser.parse_args()
    if args.stress > 0:
        return asyncio.run(run_stress(args.extended, args.stress, args.log_dir))
    return asyncio.run(run_qa(args.extended, args.log))


if __name__ == "__main__":
    sys.exit(main())
