"""Tests for NL assignment endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.webhook_handler import app
from config import settings


client = TestClient(app)


# ---------------------------------------------------------------------------
# POST /api/agent/assign-preview
# ---------------------------------------------------------------------------

def test_assign_preview_demo_mode_no_api_key(monkeypatch) -> None:
    """Without OPENROUTER_API_KEY returns a demo assignment for each phase."""
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = client.post("/api/agent/assign-preview", json={
        "project_id": 1,
        "text": "Алексей на первый этап",
        "users": [{"id": 5, "name": "Алексей", "last_name": "Петров"}],
        "phases": ["Этап 1", "Этап 2"],
    })
    assert r.status_code == 200
    data = r.json()
    assert "assignments" in data
    assert len(data["assignments"]) == 2
    assert all(a["responsible_id"] == 1 for a in data["assignments"])


def test_assign_preview_rejects_empty_text(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = client.post("/api/agent/assign-preview", json={
        "project_id": 1,
        "text": "   ",
        "users": [],
        "phases": [],
    })
    assert r.status_code == 400


def test_assign_preview_rejects_invalid_json() -> None:
    r = client.post(
        "/api/agent/assign-preview",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/agent/apply-assignments
# ---------------------------------------------------------------------------

def test_apply_assignments_rejects_missing_fields() -> None:
    r = client.post("/api/agent/apply-assignments", json={})
    assert r.status_code == 400


def test_apply_assignments_empty_phase_map_returns_zero() -> None:
    r = client.post("/api/agent/apply-assignments", json={
        "project_id": 1,
        "assignments": [{"phase": "", "responsible_id": 5}],
    })
    assert r.status_code == 200
    assert r.json()["updated"] == 0


def test_apply_assignments_rejects_invalid_json() -> None:
    r = client.post(
        "/api/agent/apply-assignments",
        content=b"oops",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/members
# ---------------------------------------------------------------------------

def test_members_returns_404_for_unknown_project() -> None:
    r = client.get("/api/projects/99999/members")
    assert r.status_code == 404


def test_members_returns_list_for_known_project(monkeypatch) -> None:
    """Stubs BitrixClient.call to return a fake group user list."""
    import app.webhook_handler as wh

    async def fake_call(self: object, method: str, params: dict) -> dict:
        if method == "sonet_group.user.get":
            return {"result": [
                {"USER_ID": "5", "USER_NAME": "Иван", "USER_LAST_NAME": "Петров"},
            ]}
        return {}

    from bitrix.client import BitrixClient
    monkeypatch.setattr(BitrixClient, "call", fake_call)

    # Insert a fake project so the SQL check passes.
    import asyncio
    from db.database import get_db

    async def seed() -> None:
        async with get_db() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO projects (id, name) VALUES (9001, 'Test')"
            )
            await conn.commit()

    asyncio.get_event_loop().run_until_complete(seed())

    r = client.get("/api/projects/9001/members")
    assert r.status_code == 200
    members = r.json()
    assert isinstance(members, list)
    assert members[0]["id"] == 5
    assert members[0]["name"] == "Иван"
