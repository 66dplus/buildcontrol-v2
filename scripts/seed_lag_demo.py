"""
Fixes + demo data on top of the VPS-synced DB:
  1. Backfill materials.cost_plan = price_plan * qty_plan where cost_plan is 0
     (synced Bitrix projects often have the "Стоим. план" property unset).
  2. Insert a snapshot at today's date for every existing project that has actuals,
     so the "Факт" timeline line shows up at all.
  3. Create test project 9001 "Тест: ЖК Просрочка" — overdue plan dates, low
     completion %, and a multi-day snapshot trail showing actual lagging behind
     plan. Gives the AI assistant something concrete to reason about.

Re-run safe: test project is wiped and re-seeded each time.
Run:
    python scripts/seed_lag_demo.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.database import get_db  # noqa: E402
from db import repo  # noqa: E402


TEST_PROJECT_ID = 9001
TEST_PROJECT_NAME = "Тест: ЖК Просрочка"


async def backfill_cost_plan(conn) -> int:
    cur = await conn.execute(
        """
        UPDATE materials
        SET cost_plan = price_plan * qty_plan
        WHERE cost_plan = 0 AND price_plan > 0 AND qty_plan > 0
        """
    )
    await conn.commit()
    return cur.rowcount


async def snapshot_existing_projects(conn) -> int:
    today = date.today().isoformat()
    inserted = 0
    async with conn.execute(
        "SELECT id FROM projects WHERE id != ?", (TEST_PROJECT_ID,)
    ) as cur:
        project_ids = [r[0] for r in await cur.fetchall()]

    for pid in project_ids:
        async with conn.execute(
            "SELECT COALESCE(SUM(cost_actual), 0) FROM materials WHERE project_id=?", (pid,)
        ) as c:
            mat = (await c.fetchone())[0]
        async with conn.execute(
            "SELECT COALESCE(SUM(payroll_actual), 0) FROM labor WHERE project_id=?", (pid,)
        ) as c:
            lab = (await c.fetchone())[0]
        async with conn.execute(
            "SELECT COALESCE(SUM(total_actual), 0) FROM equipment_items WHERE project_id=?", (pid,)
        ) as c:
            eq = (await c.fetchone())[0]

        total = mat + lab + eq
        if total <= 0:
            continue

        await conn.execute(
            """
            INSERT INTO budget_snapshots(project_id, snapshot_date, mat_actual, lab_actual, eq_actual, total_actual)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, snapshot_date) DO UPDATE SET
                mat_actual=excluded.mat_actual,
                lab_actual=excluded.lab_actual,
                eq_actual=excluded.eq_actual,
                total_actual=excluded.total_actual
            """,
            (pid, today, mat, lab, eq, total),
        )
        inserted += 1
    await conn.commit()
    return inserted


async def seed_test_project(conn) -> None:
    today = date.today()

    for tbl in ("budget_snapshots", "materials", "labor", "equipment_items", "tasks", "budget_phases"):
        await conn.execute(f"DELETE FROM {tbl} WHERE project_id=?", (TEST_PROJECT_ID,))
    await conn.commit()

    await repo.upsert_project(conn, TEST_PROJECT_ID, TEST_PROJECT_NAME)

    phases = [
        ("1. Подготовительные работы", 12_000_000, 6_500_000),
        ("2. Земляные и фундамент",    28_000_000, 9_000_000),
        ("3. Несущие конструкции",     35_000_000, 4_000_000),
    ]
    for name, plan, actual in phases:
        mat_p = round(plan * 0.55)
        lab_p = round(plan * 0.30)
        eq_p  = plan - mat_p - lab_p
        mat_a = round(actual * 0.55)
        lab_a = round(actual * 0.30)
        eq_a  = actual - mat_a - lab_a
        await repo.upsert_budget_phase(
            conn, TEST_PROJECT_ID, name,
            materials_plan=mat_p, labor_plan=lab_p, equipment_plan=eq_p, total_plan=plan,
            materials_actual=mat_a, labor_actual=lab_a, equipment_actual=eq_a, total_actual=actual,
        )

    tasks = [
        ("1. Подготовительные работы", "Временные здания",      -60, -40,  4_000_000, 2_500_000, 60),
        ("1. Подготовительные работы", "Ограждение площадки",   -55, -35,  3_500_000, 2_000_000, 55),
        ("1. Подготовительные работы", "Подвод коммуникаций",   -45, -20,  4_500_000, 2_000_000, 40),
        ("2. Земляные и фундамент",    "Разработка котлована",  -40, -15,  9_000_000, 4_500_000, 45),
        ("2. Земляные и фундамент",    "Свайное поле",          -30,  -5, 12_000_000, 3_500_000, 25),
        ("2. Земляные и фундамент",    "Ростверк",              -20,  10,  7_000_000, 1_000_000, 10),
        ("3. Несущие конструкции",     "Колонны 1-3 этаж",      -10,  30, 15_000_000, 2_500_000, 15),
        ("3. Несущие конструкции",     "Перекрытия 1-3 этаж",     5,  60, 12_000_000, 1_000_000,  5),
        ("3. Несущие конструкции",     "Лестничные клетки",      15,  70,  8_000_000,   500_000,  0),
    ]
    for phase, name, s_off, e_off, plan, actual, pct in tasks:
        await repo.upsert_task(
            conn, TEST_PROJECT_ID, phase, name,
            date_start_plan=(today + timedelta(days=s_off)).isoformat(),
            date_end_plan=(today + timedelta(days=e_off)).isoformat(),
            date_start_actual=(today + timedelta(days=s_off + 2)).isoformat() if pct > 0 else None,
            budget_plan=plan, budget_actual=actual, completion_pct=pct,
        )

    materials = [
        ("1. Подготовительные работы", "Ограждение площадки", "Профлист С8",       "м²",   850,  3000),
        ("1. Подготовительные работы", "Ограждение площадки", "Брус 100×100",      "м³",  12000,   30),
        ("2. Земляные и фундамент",    "Свайное поле",        "Свая буронабивная", "шт",  85000,   80),
        ("2. Земляные и фундамент",    "Ростверк",            "Бетон М400",        "м³",   6200,  500),
        ("2. Земляные и фундамент",    "Ростверк",            "Арматура AIII Ø16", "т",   78000,   25),
        ("3. Несущие конструкции",     "Колонны 1-3 этаж",    "Бетон М500",        "м³",   7400,  650),
        ("3. Несущие конструкции",     "Колонны 1-3 этаж",    "Арматура AIII Ø20", "т",   80000,   45),
    ]
    for phase, task_name, mat, unit, price, qty in materials:
        bought = round(qty * 0.4)
        consumed = round(qty * 0.35)
        await repo.upsert_material(
            conn, TEST_PROJECT_ID, phase, task_name, mat,
            unit=unit, price_plan=price, qty_plan=qty, cost_plan=price * qty,
            price_actual=price * 1.05, qty_bought=bought, qty_consumed=consumed,
            qty_stock=bought - consumed, cost_actual=consumed * price * 1.05,
        )

    labor = [
        ("1. Подготовительные работы", "Ограждение площадки",  "Монтажник",   1200,  800),
        ("2. Земляные и фундамент",    "Свайное поле",         "Свайщик",     1500, 2400),
        ("2. Земляные и фундамент",    "Ростверк",             "Бетонщик",    1100, 1800),
        ("3. Несущие конструкции",     "Колонны 1-3 этаж",     "Арматурщик",  1300, 3000),
        ("3. Несущие конструкции",     "Перекрытия 1-3 этаж",  "Бетонщик",    1100, 2200),
    ]
    for phase, task_name, spec, rate, hp in labor:
        ha = round(hp * 0.30)
        await repo.upsert_labor(
            conn, TEST_PROJECT_ID, phase, task_name, spec,
            rate=rate, hours_plan=hp, payroll_plan=rate * hp,
            hours_actual=ha, payroll_actual=ha * rate,
        )

    equipment = [
        ("2. Земляные и фундамент",    "Разработка котлована", "Экскаватор JCB",  3500,  400),
        ("2. Земляные и фундамент",    "Свайное поле",         "Установка БГ-12", 8000,  500),
        ("3. Несущие конструкции",     "Колонны 1-3 этаж",     "Башенный кран",   4500, 1200),
    ]
    for phase, task_name, eq_name, price, hp in equipment:
        ha = round(hp * 0.25)
        await repo.upsert_equipment(
            conn, TEST_PROJECT_ID, phase, task_name, eq_name,
            price_per_hour=price, hours_plan=hp, total_plan=price * hp,
            hours_actual=ha, total_actual=ha * price,
        )

    # Snapshots: 6 weekly points, actual ramps to 19.5M while plan-to-today ~32M.
    total_actual_now = sum(a for _, _, a in phases)  # 19.5M
    mat_share = 0.55
    lab_share = 0.30
    eq_share  = 0.15

    ramp = [0.05, 0.15, 0.30, 0.50, 0.75, 1.00]
    days_back = [60, 45, 30, 20, 10, 0]
    for d_off, k in zip(days_back, ramp):
        d = (today - timedelta(days=d_off)).isoformat()
        tot = total_actual_now * k
        await conn.execute(
            """
            INSERT INTO budget_snapshots(project_id, snapshot_date, mat_actual, lab_actual, eq_actual, total_actual)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, snapshot_date) DO UPDATE SET
                mat_actual=excluded.mat_actual, lab_actual=excluded.lab_actual,
                eq_actual=excluded.eq_actual,  total_actual=excluded.total_actual
            """,
            (TEST_PROJECT_ID, d, tot * mat_share, tot * lab_share, tot * eq_share, tot),
        )
    await conn.commit()


async def main() -> None:
    async with get_db() as conn:
        n_cost = await backfill_cost_plan(conn)
        print(f"cost_plan backfilled: {n_cost} rows")

        await seed_test_project(conn)
        print(f"Test project {TEST_PROJECT_ID} ({TEST_PROJECT_NAME}) seeded.")

        n_snap = await snapshot_existing_projects(conn)
        print(f"Snapshots inserted for {n_snap} existing projects (today).")


if __name__ == "__main__":
    asyncio.run(main())
