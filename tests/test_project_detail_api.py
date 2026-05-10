"""Tests for SPA Project Detail endpoints (tasks/materials/labor/equipment-all)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from app.webhook_handler import app
from config import settings
from db import repo

SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    db_file = tmp_path / "detail.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    async def _seed():
        async with aiosqlite.connect(str(db_file)) as conn:
            await conn.executescript(schema)
            await conn.commit()
            await repo.upsert_project(conn, 7, "Тестовый проект")
            # Tasks across two phases
            await repo.upsert_task(
                conn, 7, "Каркас", "Армирование",
                budget_plan=2_000_000, completion_pct=80,
                date_start_plan="2026-04-01", date_end_plan="2026-04-30",
                stage_id="DT123_5", stage_name="В работе",
            )
            await repo.upsert_task(
                conn, 7, "Каркас", "Бетонирование",
                budget_plan=3_000_000, completion_pct=20,
                date_start_plan="2026-05-01",
            )
            await repo.upsert_task(
                conn, 7, "Отделка", "Штукатурка",
                budget_plan=1_500_000, completion_pct=0,
            )
            # Materials — one in Каркас/Армирование, one in Отделка/Штукатурка
            await repo.upsert_material(
                conn, 7, "Каркас", "Армирование", "Арматура А500С",
                unit="т", price_plan=80_000, qty_plan=10, cost_plan=800_000,
                price_actual=82_000, qty_bought=10, qty_consumed=8,
                qty_stock=2, cost_actual=820_000,
            )
            await repo.upsert_material(
                conn, 7, "Отделка", "Штукатурка", "Гипс",
                unit="мешок", price_plan=300, qty_plan=200, cost_plan=60_000,
            )
            # Labor
            await repo.upsert_labor(
                conn, 7, "Каркас", "Армирование", "Арматурщик",
                rate=500, hours_plan=200, payroll_plan=100_000,
                hours_actual=210, payroll_actual=105_000,
            )
            # Equipment
            await repo.upsert_equipment(
                conn, 7, "Каркас", "Бетонирование", "Бетононасос",
                price_per_hour=2_500, hours_plan=40, total_plan=100_000,
                hours_actual=42, total_actual=105_000,
            )

    asyncio.get_event_loop().run_until_complete(_seed())
    return db_file


def test_tasks_full_returns_all_columns(seeded_db) -> None:
    client = TestClient(app)
    r = client.get("/api/projects/7/tasks-full")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    armir = next(t for t in rows if t["task_name"] == "Армирование")
    assert armir["phase"] == "Каркас"
    assert armir["budget_plan"] == 2_000_000
    assert armir["completion_pct"] == 80
    assert armir["date_start_plan"] == "2026-04-01"
    assert armir["stage_name"] == "В работе"


def test_materials_all_returns_everything_when_unfiltered(seeded_db) -> None:
    client = TestClient(app)
    rows = client.get("/api/projects/7/materials-all").json()
    assert len(rows) == 2
    names = {r["material_name"] for r in rows}
    assert names == {"Арматура А500С", "Гипс"}


def test_materials_all_filters_by_phase(seeded_db) -> None:
    client = TestClient(app)
    rows = client.get("/api/projects/7/materials-all?phase=Каркас").json()
    assert len(rows) == 1
    assert rows[0]["material_name"] == "Арматура А500С"


def test_materials_all_filters_by_phase_and_task(seeded_db) -> None:
    client = TestClient(app)
    rows = client.get(
        "/api/projects/7/materials-all?phase=Отделка&task=Штукатурка"
    ).json()
    assert len(rows) == 1
    assert rows[0]["material_name"] == "Гипс"


def test_labor_all_returns_rows(seeded_db) -> None:
    client = TestClient(app)
    rows = client.get("/api/projects/7/labor-all").json()
    assert len(rows) == 1
    assert rows[0]["specialty"] == "Арматурщик"
    assert rows[0]["hours_actual"] == 210


def test_equipment_all_returns_rows(seeded_db) -> None:
    client = TestClient(app)
    rows = client.get("/api/projects/7/equipment-all").json()
    assert len(rows) == 1
    assert rows[0]["equipment_name"] == "Бетононасос"


def test_endpoints_return_empty_for_unknown_project(seeded_db) -> None:
    client = TestClient(app)
    for path in ("tasks-full", "materials-all", "labor-all", "equipment-all"):
        r = client.get(f"/api/projects/9999/{path}")
        assert r.status_code == 200, path
        assert r.json() == [], path
