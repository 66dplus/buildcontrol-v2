"""Tests for the SPA Dashboard endpoints — read directly from SQLite."""

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
    """Point settings.db_path at a temp SQLite file with two seeded projects."""
    db_file = tmp_path / "dashboard.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    async def _seed():
        async with aiosqlite.connect(str(db_file)) as conn:
            await conn.executescript(schema)
            await conn.commit()
            await repo.upsert_project(conn, 101, "Торговый центр")
            await repo.upsert_project(conn, 202, "Склад на Северном")
            # Project 101 — on track (variance ~5%)
            await repo.upsert_budget_phase(
                conn, 101, "Каркас",
                materials_plan=10_000_000, labor_plan=5_000_000, equipment_plan=2_000_000,
                total_plan=17_000_000,
                materials_actual=10_500_000, labor_actual=5_200_000, equipment_actual=2_100_000,
                total_actual=17_800_000,
            )
            await repo.upsert_budget_phase(
                conn, 101, "Отделка",
                materials_plan=8_000_000, labor_plan=4_000_000, equipment_plan=1_000_000,
                total_plan=13_000_000,
                materials_actual=8_100_000, labor_actual=4_050_000, equipment_actual=1_050_000,
                total_actual=13_200_000,
            )
            # Project 202 — overrun (variance ~25%)
            await repo.upsert_budget_phase(
                conn, 202, "Фундамент",
                materials_plan=4_000_000, labor_plan=2_000_000, equipment_plan=1_000_000,
                total_plan=7_000_000,
                materials_actual=5_500_000, labor_actual=2_400_000, equipment_actual=900_000,
                total_actual=8_800_000,
            )

    asyncio.get_event_loop().run_until_complete(_seed())
    return db_file


def test_phases_endpoint_returns_seeded_rows(seeded_db) -> None:
    client = TestClient(app)
    r = client.get("/api/projects/101/phases")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    names = {p["phase_name"] for p in body}
    assert names == {"Каркас", "Отделка"}
    karkas = next(p for p in body if p["phase_name"] == "Каркас")
    assert karkas["total_plan"] == 17_000_000
    assert karkas["total_actual"] == 17_800_000


def test_phases_endpoint_empty_for_unknown_project(seeded_db) -> None:
    client = TestClient(app)
    r = client.get("/api/projects/9999/phases")
    assert r.status_code == 200
    assert r.json() == []


def test_dashboard_summary_returns_per_project_rows(seeded_db) -> None:
    client = TestClient(app)
    r = client.get("/api/dashboard/summary")
    assert r.status_code == 200
    body = r.json()

    assert "projects" in body
    assert "kpi" in body
    assert len(body["projects"]) == 2

    by_id = {p["id"]: p for p in body["projects"]}
    p101 = by_id[101]
    assert p101["name"] == "Торговый центр"
    assert p101["total_plan"] == 30_000_000
    assert p101["total_actual"] == 31_000_000
    assert p101["materials_plan"] == 18_000_000
    assert p101["phase_count"] == 2
    assert 3 < p101["variance_pct"] < 4  # ≈ 3.33%

    p202 = by_id[202]
    assert p202["total_plan"] == 7_000_000
    assert p202["total_actual"] == 8_800_000
    assert 25 < p202["variance_pct"] < 26  # ≈ 25.7%


def test_dashboard_summary_kpi_aggregates_portfolio(seeded_db) -> None:
    client = TestClient(app)
    body = client.get("/api/dashboard/summary").json()
    kpi = body["kpi"]
    assert kpi["total_plan"] == 37_000_000
    assert kpi["total_actual"] == 39_800_000
    # Project 202 has variance > 15% → counted as anomaly. 101 does not.
    assert kpi["anomaly_count"] == 1


def test_dashboard_summary_handles_zero_plan(tmp_path, monkeypatch) -> None:
    """A project with no budget data shouldn't divide-by-zero."""
    db_file = tmp_path / "edge.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    async def _seed():
        async with aiosqlite.connect(str(db_file)) as conn:
            await conn.executescript(schema)
            await conn.commit()
            await repo.upsert_project(conn, 1, "Пустой проект")

    asyncio.get_event_loop().run_until_complete(_seed())
    client = TestClient(app)
    body = client.get("/api/dashboard/summary").json()
    assert body["projects"][0]["variance_pct"] == 0
    assert body["kpi"]["anomaly_count"] == 0
