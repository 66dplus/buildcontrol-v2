"""
Seed realistic demo data into the local SQLite database.

Run once:
    python scripts/seed_demo_data.py

Safe to re-run — uses INSERT OR IGNORE / INSERT OR REPLACE so existing rows
are not duplicated. Historical budget_snapshots are regenerated on each run.
"""
from __future__ import annotations

import asyncio
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

# Make sure we can import project modules from root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiosqlite
from config import settings

# ---------------------------------------------------------------------------
# Demo projects
# ---------------------------------------------------------------------------

PROJECTS = [
    {"id": 1001, "name": "ТЦ Меридиан — 1-я очередь"},
    {"id": 1002, "name": "Жилой комплекс Северный"},
    {"id": 1003, "name": "Логистический центр Восток"},
]

# ---------------------------------------------------------------------------
# Phase / task structure (same for all projects, budgets differ)
# ---------------------------------------------------------------------------

PHASES = [
    "Фундамент",
    "Каркас и перекрытия",
    "Отделочные работы",
]

TASKS_PER_PHASE = [
    # (task_name, budget_plan factor, days_start_offset, duration_days)
    ("Земляные работы",         0.15, 0,   20),
    ("Свайное основание",       0.35, 20,  35),
    ("Бетонирование ростверка", 0.50, 55,  25),
]

TASKS_FRAME = [
    ("Монтаж колонн",           0.30, 0,   30),
    ("Перекрытия 1-го этажа",   0.35, 30,  35),
    ("Кровельные работы",       0.35, 65,  30),
]

TASKS_FINISH = [
    ("Штукатурные работы",      0.40, 0,   40),
    ("Электромонтаж",           0.25, 30,  35),
    ("Финальная отделка",       0.35, 60,  40),
]

PHASE_TASKS = {
    "Фундамент":             TASKS_PER_PHASE,
    "Каркас и перекрытия":   TASKS_FRAME,
    "Отделочные работы":     TASKS_FINISH,
}

# ---------------------------------------------------------------------------
# Budget multipliers per project (total plan, ₽)
# ---------------------------------------------------------------------------

PROJECT_BUDGETS = {
    1001: 85_000_000,
    1002: 120_000_000,
    1003: 55_000_000,
}

PHASE_SPLIT = {
    "Фундамент":             0.25,
    "Каркас и перекрытия":   0.45,
    "Отделочные работы":     0.30,
}

# ---------------------------------------------------------------------------
# Materials per phase
# ---------------------------------------------------------------------------

MATERIALS_BY_PHASE = {
    "Фундамент": [
        ("Арматура А500С",   "т",    75_000, 8),
        ("Бетон М300",       "м³",   6_500,  80),
        ("Песок строительный","м³",   1_200,  120),
    ],
    "Каркас и перекрытия": [
        ("Металлопрокат ст.3", "т",   68_000, 15),
        ("Бетон М400",         "м³",   7_200,  150),
        ("Кирпич рядовой",     "шт",   14,     25_000),
        ("Пиломатериал",       "м³",   22_000, 5),
    ],
    "Отделочные работы": [
        ("Гипсокартон",       "лист",  450,    600),
        ("Краска интерьерная","кг",    280,    800),
        ("Плитка керамическая","м²",   1_800,  350),
        ("Электрокабель",     "м",     85,     2_000),
    ],
}

# ---------------------------------------------------------------------------
# Labor per phase
# ---------------------------------------------------------------------------

LABOR_BY_PHASE = {
    "Фундамент": [
        ("Арматурщик",    420, 400),
        ("Бетонщик",      420, 320),
        ("Разнорабочий",  300, 160),
    ],
    "Каркас и перекрытия": [
        ("Монтажник металлоконструкций", 520, 480),
        ("Бетонщик",                    420, 380),
        ("Каменщик",                    480, 240),
    ],
    "Отделочные работы": [
        ("Штукатур",         400, 480),
        ("Маляр",            380, 320),
        ("Электрик",         550, 280),
        ("Плиточник",        460, 200),
    ],
}

# ---------------------------------------------------------------------------
# Equipment per phase
# ---------------------------------------------------------------------------

EQUIPMENT_BY_PHASE = {
    "Фундамент": [
        ("Экскаватор Komatsu", 4_500, 120),
        ("Бетоносмеситель",    1_800, 80),
    ],
    "Каркас и перекрытия": [
        ("Башенный кран",   6_500, 200),
        ("Автобетононасос", 5_200, 60),
    ],
    "Отделочные работы": [
        ("Подъёмник строительный", 2_800, 80),
    ],
}

# ---------------------------------------------------------------------------
# Actuals ratios (actual / plan) — some overruns to make chart interesting
# ---------------------------------------------------------------------------

ACTUAL_RATIOS = {
    1001: {"mat": 1.08, "lab": 1.05, "eq": 0.97},  # slight overrun
    1002: {"mat": 1.18, "lab": 1.12, "eq": 1.05},  # significant overrun
    1003: {"mat": 0.95, "lab": 0.98, "eq": 0.90},  # on budget
}

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def seed(db_path: str) -> None:
    random.seed(42)
    project_start = date(2026, 1, 15)

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys=OFF")

        for proj in PROJECTS:
            pid = proj["id"]
            pname = proj["name"]
            total_budget = PROJECT_BUDGETS[pid]
            ratios = ACTUAL_RATIOS[pid]

            # Project
            await conn.execute(
                "INSERT OR IGNORE INTO projects(id, name, is_archived) VALUES(?,?,0)",
                (pid, pname),
            )

            phase_start = project_start
            for phase_name in PHASES:
                phase_budget = total_budget * PHASE_SPLIT[phase_name]
                phase_mat_plan = phase_budget * 0.55
                phase_lab_plan = phase_budget * 0.30
                phase_eq_plan  = phase_budget * 0.15

                # budget_phases row
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO budget_phases(
                        project_id, phase_name,
                        materials_plan, labor_plan, equipment_plan, total_plan,
                        materials_actual, labor_actual, equipment_actual, total_actual
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        pid, phase_name,
                        phase_mat_plan, phase_lab_plan, phase_eq_plan, phase_budget,
                        phase_mat_plan * ratios["mat"],
                        phase_lab_plan * ratios["lab"],
                        phase_eq_plan  * ratios["eq"],
                        phase_budget * (
                            0.55 * ratios["mat"] + 0.30 * ratios["lab"] + 0.15 * ratios["eq"]
                        ),
                    ),
                )

                # Tasks
                tasks = PHASE_TASKS[phase_name]
                task_start = phase_start
                for task_name, bfactor, day_offset, duration in tasks:
                    t_start = phase_start + timedelta(days=day_offset)
                    t_end   = t_start + timedelta(days=duration)
                    t_budget_plan = phase_budget * bfactor
                    t_budget_act  = t_budget_plan * (
                        0.55 * ratios["mat"] + 0.30 * ratios["lab"] + 0.15 * ratios["eq"]
                    )
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO tasks(
                            project_id, phase, task_name,
                            date_start_plan, date_end_plan,
                            date_start_actual, date_end_actual,
                            budget_plan, budget_actual, completion_pct, stage_name
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            pid, phase_name, task_name,
                            t_start.isoformat(), t_end.isoformat(),
                            t_start.isoformat(), None,
                            t_budget_plan, t_budget_act,
                            random.randint(60, 100),
                            "В работе",
                        ),
                    )

                # Phase end = max task end
                phase_end = phase_start + timedelta(days=max(d + dur for _, _, d, dur in tasks))

                # Materials
                for mat_name, unit, price_plan, qty_plan in MATERIALS_BY_PHASE[phase_name]:
                    cost_plan   = price_plan * qty_plan
                    price_act   = price_plan * (1 + random.uniform(-0.05, 0.15))
                    qty_bought  = qty_plan * random.uniform(0.8, 1.1)
                    qty_consumed= qty_plan * random.uniform(0.7, 1.0)
                    qty_stock   = max(0, qty_bought - qty_consumed)
                    cost_actual = price_act * qty_consumed
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO materials(
                            project_id, phase, task_name, material_name, unit,
                            price_plan, qty_plan, cost_plan,
                            price_actual, qty_bought, qty_consumed, qty_stock, cost_actual
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            pid, phase_name, tasks[0][0], mat_name, unit,
                            price_plan, qty_plan, cost_plan,
                            price_act, qty_bought, qty_consumed, qty_stock, cost_actual,
                        ),
                    )

                # Labor
                for specialty, rate, hours_plan in LABOR_BY_PHASE[phase_name]:
                    payroll_plan   = rate * hours_plan
                    hours_actual   = hours_plan * random.uniform(0.9, 1.15)
                    payroll_actual = rate * hours_actual
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO labor(
                            project_id, phase, task_name, specialty, rate,
                            hours_plan, payroll_plan, hours_actual, payroll_actual
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            pid, phase_name, tasks[0][0], specialty, rate,
                            hours_plan, payroll_plan, hours_actual, payroll_actual,
                        ),
                    )

                # Equipment
                for eq_name, price_per_hour, hours_plan in EQUIPMENT_BY_PHASE[phase_name]:
                    total_plan   = price_per_hour * hours_plan
                    hours_actual = hours_plan * random.uniform(0.85, 1.1)
                    total_actual = price_per_hour * hours_actual
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO equipment_items(
                            project_id, phase, task_name, equipment_name,
                            price_per_hour, hours_plan, total_plan, hours_actual, total_actual
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            pid, phase_name, tasks[0][0], eq_name,
                            price_per_hour, hours_plan, total_plan, hours_actual, total_actual,
                        ),
                    )

                phase_start = phase_end + timedelta(days=5)

            # Historical budget_snapshots — 3 months of weekly reports
            # Simulate a gradual ramp-up from 0 to final actuals
            phases_data = []
            async with conn.execute(
                "SELECT materials_actual, labor_actual, equipment_actual, total_actual "
                "FROM budget_phases WHERE project_id=?",
                (pid,),
            ) as cur:
                phases_data = await cur.fetchall()

            final_mat = sum(r[0] or 0 for r in phases_data)
            final_lab = sum(r[1] or 0 for r in phases_data)
            final_eq  = sum(r[2] or 0 for r in phases_data)
            final_tot = sum(r[3] or 0 for r in phases_data)

            # Delete existing snapshots for this project before re-seeding
            await conn.execute("DELETE FROM budget_snapshots WHERE project_id=?", (pid,))

            snap_start = project_start
            snap_today = date.today()
            num_weeks  = max(1, (snap_today - snap_start).days // 7)

            for week_idx in range(num_weeks + 1):
                snap_date = snap_start + timedelta(weeks=week_idx)
                if snap_date > snap_today:
                    snap_date = snap_today
                # S-curve progress factor (slow start, fast middle, slow end)
                t = week_idx / max(num_weeks, 1)
                # Logistic curve centered at t=0.4 for a realistic ramp
                progress = 1 / (1 + math.exp(-10 * (t - 0.4)))
                noise = random.uniform(0.97, 1.03)
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO budget_snapshots(
                        project_id, snapshot_date, mat_actual, lab_actual, eq_actual, total_actual
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        pid,
                        snap_date.isoformat(),
                        final_mat * progress * noise,
                        final_lab * progress * noise,
                        final_eq  * progress * noise,
                        final_tot * progress * noise,
                    ),
                )
                if snap_date >= snap_today:
                    break

        await conn.commit()
        print(f"Seeded {len(PROJECTS)} projects into {db_path}")
        print("Tables: projects, budget_phases, tasks, materials, labor, equipment_items, budget_snapshots")


if __name__ == "__main__":
    asyncio.run(seed(settings.db_path))
