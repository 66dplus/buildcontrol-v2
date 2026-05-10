"""Tests for the math executed by POST /api/report.

The handler in ``app.webhook_handler`` delegates the actual deltas to
``repo.update_material_after_report`` / ``update_labor_after_report`` /
``update_equipment_after_report`` and then triggers cascade. These are the
silent-corruption hotspots: every cumulative figure on the director's
dashboard ultimately comes from this path.

We test the delta math + cascade integration directly against an in-memory
SQLite. Auth and idempotency are covered separately in
``test_auth_middleware.py`` and ``test_idempotency.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import aiosqlite
import pytest
import pytest_asyncio

from db import repo


SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[aiosqlite.Connection]:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(":memory:") as c:
        c.row_factory = aiosqlite.Row
        await c.executescript(schema)
        await repo.upsert_project(c, 1, "Project A")
        # Seed: a task with one material, one labor row, one equipment row.
        await repo.upsert_task(c, 1, "Фаза 1", "Задача 1")
        await c.execute(
            "INSERT INTO materials (project_id, phase, task_name, material_name, "
            "unit, price_plan, qty_plan, cost_plan, "
            "price_actual, qty_bought, qty_consumed, qty_stock, cost_actual) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "Фаза 1", "Задача 1", "Бетон М400",
             "м³", 5000.0, 10.0, 50000.0,
             5200.0, 10.0, 0.0, 10.0, 0.0),
        )
        await c.execute(
            "INSERT INTO labor (project_id, phase, task_name, specialty, "
            "rate, hours_plan, payroll_plan, hours_actual, payroll_actual) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "Фаза 1", "Задача 1", "Каменщик", 500.0, 40.0, 20000.0, 0.0, 0.0),
        )
        await c.execute(
            "INSERT INTO equipment_items (project_id, phase, task_name, equipment_name, "
            "price_per_hour, hours_plan, total_plan, hours_actual, total_actual) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "Фаза 1", "Задача 1", "Кран", 1500.0, 8.0, 12000.0, 0.0, 0.0),
        )
        await repo.upsert_budget_phase(
            c, project_id=1, phase_name="Фаза 1",
            materials_plan=50000.0, labor_plan=20000.0,
            equipment_plan=12000.0, total_plan=82000.0,
        )
        await c.commit()
        yield c


# ---------------------------------------------------------------------------
# Material delta: qty_consumed += X, qty_stock -= X, cost_actual += X*price
# This is what the handler at app/webhook_handler.py:1740-1755 does.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_material_report_increments_consumed_and_decrements_stock(
    conn: aiosqlite.Connection,
) -> None:
    # Foreman reports 3 м³ consumed. Price is 5200 (price_actual fallback).
    qty = 3.0
    price = 5200.0
    await repo.update_material_after_report(
        conn, 1, "Фаза 1", "Задача 1", "Бетон М400", qty, qty * price,
    )
    row = await repo.get_material_row(conn, 1, "Фаза 1", "Задача 1", "Бетон М400")
    assert row is not None
    assert row["qty_consumed"] == 3.0
    assert row["qty_stock"] == 7.0  # 10 - 3
    assert row["cost_actual"] == 15600.0


@pytest.mark.asyncio
async def test_repeated_material_reports_accumulate(conn: aiosqlite.Connection) -> None:
    # Two foreman reports across two days — deltas must add, not replace.
    await repo.update_material_after_report(conn, 1, "Фаза 1", "Задача 1", "Бетон М400", 3.0, 15600.0)
    await repo.update_material_after_report(conn, 1, "Фаза 1", "Задача 1", "Бетон М400", 2.0, 10400.0)
    row = await repo.get_material_row(conn, 1, "Фаза 1", "Задача 1", "Бетон М400")
    assert row is not None
    assert row["qty_consumed"] == 5.0
    assert row["qty_stock"] == 5.0
    assert row["cost_actual"] == 26000.0


# ---------------------------------------------------------------------------
# Labor delta: hours_actual += X, payroll_actual += X*rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_labor_report_increments_hours_and_payroll(
    conn: aiosqlite.Connection,
) -> None:
    hours = 8.0
    rate = 500.0
    await repo.update_labor_after_report(
        conn, 1, "Фаза 1", "Задача 1", "Каменщик", hours, hours * rate,
    )
    row = await repo.get_labor_row(conn, 1, "Фаза 1", "Задача 1", "Каменщик")
    assert row is not None
    assert row["hours_actual"] == 8.0
    assert row["payroll_actual"] == 4000.0


# ---------------------------------------------------------------------------
# Equipment delta: hours_actual += X, total_actual += X*price_per_hour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_equipment_report_increments_hours_and_total(
    conn: aiosqlite.Connection,
) -> None:
    hours = 4.0
    price = 1500.0
    await repo.update_equipment_after_report(
        conn, 1, "Фаза 1", "Задача 1", "Кран", hours, hours * price,
    )
    row = await repo.get_equipment_row(conn, 1, "Фаза 1", "Задача 1", "Кран")
    assert row is not None
    assert row["hours_actual"] == 4.0
    assert row["total_actual"] == 6000.0


# ---------------------------------------------------------------------------
# End-to-end: report deltas + cascade → tasks.budget_actual + budget_phases
# This is the path POST /api/report walks through. If any step is broken,
# the director sees wrong numbers in their Bitrix24 dashboard.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_report_flow_propagates_to_phase_budget(
    conn: aiosqlite.Connection,
) -> None:
    # Foreman reports: 3 м³ concrete, 8 hours of mason, 4 hours of crane.
    await repo.update_material_after_report(conn, 1, "Фаза 1", "Задача 1", "Бетон М400", 3.0, 15600.0)
    await repo.update_labor_after_report(conn, 1, "Фаза 1", "Задача 1", "Каменщик", 8.0, 4000.0)
    await repo.update_equipment_after_report(conn, 1, "Фаза 1", "Задача 1", "Кран", 4.0, 6000.0)

    # Cascade: per-task budget, then per-phase budget.
    task_total = await repo.cascade_task_budget(conn, 1, "Фаза 1", "Задача 1")
    assert task_total == 25600.0  # 15600 + 4000 + 6000

    phase_totals = await repo.cascade_phase_budget(conn, 1, "Фаза 1")
    assert phase_totals == {
        "materials_actual": 15600.0,
        "labor_actual": 4000.0,
        "equipment_actual": 6000.0,
        "total_actual": 25600.0,
    }


@pytest.mark.asyncio
async def test_double_submit_without_idempotency_doubles_deltas(
    conn: aiosqlite.Connection,
) -> None:
    # This is the exact bug ``Idempotency-Key`` exists to prevent. We are
    # NOT using the cache here — just confirming the math doubles when
    # the same report is applied twice. The cache is verified end-to-end
    # in tests/test_idempotency.py.
    for _ in range(2):
        await repo.update_material_after_report(
            conn, 1, "Фаза 1", "Задача 1", "Бетон М400", 3.0, 15600.0,
        )

    row = await repo.get_material_row(conn, 1, "Фаза 1", "Задача 1", "Бетон М400")
    assert row is not None
    # qty_consumed doubled, qty_stock now NEGATIVE (over-consumed). This is
    # the visible failure mode the idempotency cache prevents on the
    # request side.
    assert row["qty_consumed"] == 6.0
    assert row["qty_stock"] == 4.0
    assert row["cost_actual"] == 31200.0


@pytest.mark.asyncio
async def test_report_for_unknown_material_is_noop(
    conn: aiosqlite.Connection,
) -> None:
    # If the material name doesn't match any seeded row, the UPDATE matches
    # zero rows and silently does nothing. Nothing else in the table changes.
    await repo.update_material_after_report(
        conn, 1, "Фаза 1", "Задача 1", "Не существует", 5.0, 25000.0,
    )
    # The known row must be untouched.
    row = await repo.get_material_row(conn, 1, "Фаза 1", "Задача 1", "Бетон М400")
    assert row is not None
    assert row["qty_consumed"] == 0.0
    assert row["cost_actual"] == 0.0


@pytest.mark.asyncio
async def test_report_scoped_to_correct_task(conn: aiosqlite.Connection) -> None:
    # Same material name in two tasks. Reporting against task 1 must NOT
    # touch the task 2 row.
    await conn.execute(
        "INSERT INTO materials (project_id, phase, task_name, material_name, "
        "qty_stock, cost_actual) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Фаза 1", "Задача 2", "Бетон М400", 100.0, 0.0),
    )
    await conn.commit()

    await repo.update_material_after_report(
        conn, 1, "Фаза 1", "Задача 1", "Бетон М400", 3.0, 15600.0,
    )

    t1 = await repo.get_material_row(conn, 1, "Фаза 1", "Задача 1", "Бетон М400")
    t2 = await repo.get_material_row(conn, 1, "Фаза 1", "Задача 2", "Бетон М400")
    assert t1 is not None and t2 is not None
    assert t1["qty_consumed"] == 3.0
    assert t2["qty_consumed"] == 0.0  # untouched
    assert t2["qty_stock"] == 100.0  # untouched
