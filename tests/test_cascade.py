"""Tests for cascade math.

The SUM math itself lives in ``db.repo`` (``cascade_task_budget`` and
``cascade_phase_budget``); ``utils.cascade`` is a thin orchestration layer
that mirrors the SQLite result to Bitrix.

These tests run entirely offline against an in-memory SQLite, with the
Bitrix client patched to a no-op for the orchestration tests.
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
        await c.commit()
        # Seed a project so FK constraints (when on) don't bite.
        await repo.upsert_project(c, 1, "Project A")
        await repo.upsert_project(c, 2, "Project B")
        yield c


# ---------------------------------------------------------------------------
# repo.cascade_task_budget — Σ(cost_actual + payroll_actual + total_actual)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_budget_empty_returns_zero(conn: aiosqlite.Connection) -> None:
    total = await repo.cascade_task_budget(conn, 1, "Фаза 1", "Задача 1")
    assert total == 0.0


@pytest.mark.asyncio
async def test_task_budget_sums_three_categories(conn: aiosqlite.Connection) -> None:
    # 100 (mat) + 200 (labor) + 50 (equipment) = 350
    await conn.execute(
        "INSERT INTO materials (project_id, phase, task_name, material_name, cost_actual) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Фаза 1", "Задача 1", "Бетон", 100.0),
    )
    await conn.execute(
        "INSERT INTO labor (project_id, phase, task_name, specialty, payroll_actual) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Фаза 1", "Задача 1", "Каменщик", 200.0),
    )
    await conn.execute(
        "INSERT INTO equipment_items (project_id, phase, task_name, equipment_name, total_actual) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Фаза 1", "Задача 1", "Кран", 50.0),
    )
    await conn.commit()

    total = await repo.cascade_task_budget(conn, 1, "Фаза 1", "Задача 1")
    assert total == 350.0

    # And the tasks table is updated.
    await repo.upsert_task(conn, 1, "Фаза 1", "Задача 1")
    total2 = await repo.cascade_task_budget(conn, 1, "Фаза 1", "Задача 1")
    assert total2 == 350.0
    async with conn.execute(
        "SELECT budget_actual FROM tasks WHERE project_id=? AND phase=? AND task_name=?",
        (1, "Фаза 1", "Задача 1"),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["budget_actual"] == 350.0


@pytest.mark.asyncio
async def test_task_budget_scoped_to_task(conn: aiosqlite.Connection) -> None:
    # Two tasks in the same phase. cascade for task 1 must NOT pick up task 2's row.
    await conn.execute(
        "INSERT INTO materials (project_id, phase, task_name, material_name, cost_actual) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Фаза 1", "Задача 1", "Бетон", 100.0),
    )
    await conn.execute(
        "INSERT INTO materials (project_id, phase, task_name, material_name, cost_actual) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Фаза 1", "Задача 2", "Кирпич", 999.0),
    )
    await conn.commit()
    assert await repo.cascade_task_budget(conn, 1, "Фаза 1", "Задача 1") == 100.0
    assert await repo.cascade_task_budget(conn, 1, "Фаза 1", "Задача 2") == 999.0


@pytest.mark.asyncio
async def test_task_budget_scoped_to_project(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        "INSERT INTO materials (project_id, phase, task_name, material_name, cost_actual) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Фаза 1", "Задача 1", "Бетон", 100.0),
    )
    await conn.execute(
        "INSERT INTO materials (project_id, phase, task_name, material_name, cost_actual) "
        "VALUES (?, ?, ?, ?, ?)",
        (2, "Фаза 1", "Задача 1", "Бетон", 100.0),
    )
    await conn.commit()
    # Project 1 must not see project 2's row.
    assert await repo.cascade_task_budget(conn, 1, "Фаза 1", "Задача 1") == 100.0


# ---------------------------------------------------------------------------
# repo.cascade_phase_budget — per-category sums for the whole phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_budget_empty_returns_zeros(conn: aiosqlite.Connection) -> None:
    totals = await repo.cascade_phase_budget(conn, 1, "Фаза 1")
    assert totals == {
        "materials_actual": 0.0,
        "labor_actual": 0.0,
        "equipment_actual": 0.0,
        "total_actual": 0.0,
    }


@pytest.mark.asyncio
async def test_phase_budget_sums_across_tasks(conn: aiosqlite.Connection) -> None:
    # Two tasks in Фаза 1 — phase totals are the union.
    rows = [
        # phase, task, mat_cost, labor_payroll, eq_total
        ("Фаза 1", "Задача 1", 100.0, 200.0, 50.0),
        ("Фаза 1", "Задача 2", 30.0,  40.0,  20.0),
        ("Фаза 2", "Задача 3", 999.0, 999.0, 999.0),  # different phase, must be excluded
    ]
    for phase, task, mat, lab, eq in rows:
        await conn.execute(
            "INSERT INTO materials (project_id, phase, task_name, material_name, cost_actual) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, phase, task, "M", mat),
        )
        await conn.execute(
            "INSERT INTO labor (project_id, phase, task_name, specialty, payroll_actual) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, phase, task, "S", lab),
        )
        await conn.execute(
            "INSERT INTO equipment_items (project_id, phase, task_name, equipment_name, total_actual) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, phase, task, "E", eq),
        )
    # Seed budget_phases so the UPDATE actually has a row.
    await repo.upsert_budget_phase(
        conn, project_id=1, phase_name="Фаза 1",
        materials_plan=0.0, labor_plan=0.0, equipment_plan=0.0, total_plan=0.0,
    )
    await conn.commit()

    totals = await repo.cascade_phase_budget(conn, 1, "Фаза 1")
    assert totals["materials_actual"] == 130.0
    assert totals["labor_actual"] == 240.0
    assert totals["equipment_actual"] == 70.0
    assert totals["total_actual"] == 440.0

    # And budget_phases is updated.
    async with conn.execute(
        "SELECT materials_actual, labor_actual, equipment_actual, total_actual "
        "FROM budget_phases WHERE project_id=? AND phase_name=?",
        (1, "Фаза 1"),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["materials_actual"] == 130.0
    assert row["total_actual"] == 440.0


@pytest.mark.asyncio
async def test_phase_budget_idempotent_recompute(conn: aiosqlite.Connection) -> None:
    # Running cascade twice with no new data must produce the same totals
    # — guards against the very bug idempotency on /api/report exists for.
    await conn.execute(
        "INSERT INTO materials (project_id, phase, task_name, material_name, cost_actual) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Фаза 1", "Задача 1", "M", 100.0),
    )
    await repo.upsert_budget_phase(
        conn, project_id=1, phase_name="Фаза 1",
        materials_plan=0.0, labor_plan=0.0, equipment_plan=0.0, total_plan=0.0,
    )
    await conn.commit()

    t1 = await repo.cascade_phase_budget(conn, 1, "Фаза 1")
    t2 = await repo.cascade_phase_budget(conn, 1, "Фаза 1")
    assert t1 == t2
    assert t1["materials_actual"] == 100.0


# ---------------------------------------------------------------------------
# utils.cascade orchestration: SQLite update succeeds even when Bitrix fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cascade_update_task_survives_missing_bitrix_list(
    conn: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If Bitrix has no "Tasks" list (or the helper returns None), the SQLite
    # update must still happen — the foreman's report cannot be lost because
    # of a Bitrix mirror hiccup.
    from utils import cascade as cascade_mod

    await conn.execute(
        "INSERT INTO materials (project_id, phase, task_name, material_name, cost_actual) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Фаза 1", "Задача 1", "M", 100.0),
    )
    await repo.upsert_task(conn, 1, "Фаза 1", "Задача 1")
    await conn.commit()

    # Patch get_db to yield our in-memory conn instead of opening a file.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(cascade_mod, "get_db", _fake_get_db)

    # Patch the bitrix list-context helper to simulate "list not found".
    async def _no_list(client, project_id, keyword):
        return None

    monkeypatch.setattr(cascade_mod, "_bitrix_list_context", _no_list)

    class _StubClient:
        pass

    ok = await cascade_mod.cascade_update_task(_StubClient(), 1, "Фаза 1", "Задача 1")
    assert ok is True

    # SQLite was updated even though Bitrix was unavailable.
    async with conn.execute(
        "SELECT budget_actual FROM tasks WHERE project_id=? AND phase=? AND task_name=?",
        (1, "Фаза 1", "Задача 1"),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["budget_actual"] == 100.0
