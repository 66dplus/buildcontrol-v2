"""Tests for agent write-action tools and the /api/agent/confirm endpoint."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.webhook_handler import app
from app.agent_tools import PENDING_ACTIONS
from config import settings


client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_pending():
    """Ensure PENDING_ACTIONS is empty before and after each test."""
    PENDING_ACTIONS.clear()
    yield
    PENDING_ACTIONS.clear()


# ---------------------------------------------------------------------------
# /api/agent/confirm — happy path
# ---------------------------------------------------------------------------

def test_confirm_executes_known_action(monkeypatch) -> None:
    """A stored pending action is approved via the new app.agent.pending module."""
    from app.agent import pending as new_pending

    action_id = str(uuid.uuid4())
    executed: list[str] = []

    async def fake_approve(aid: str) -> dict:
        executed.append(aid)
        return {"ok": True, "result": {"action_id": aid}}

    monkeypatch.setattr(new_pending, "approve", fake_approve)
    new_pending.PENDING_ACTIONS[action_id] = {
        "tool_name": "add_comment", "args": {}, "session_id": None,
    }

    r = client.post("/api/agent/confirm", json={"action_id": action_id})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert executed == [action_id]


def test_confirm_returns_404_for_unknown_action() -> None:
    """An unknown action_id resolves to 404 (matches the legacy route's contract)."""
    from app.agent import pending as new_pending
    new_pending.PENDING_ACTIONS.clear()
    r = client.post("/api/agent/confirm", json={"action_id": "no-such-id"})
    assert r.status_code == 404
    assert r.json()["error"] == "action_not_found"


def test_confirm_rejects_missing_action_id() -> None:
    r = client.post("/api/agent/confirm", json={})
    assert r.status_code == 400


def test_confirm_rejects_invalid_json() -> None:
    r = client.post(
        "/api/agent/confirm",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# PENDING_ACTIONS store — unit tests
# ---------------------------------------------------------------------------

def test_pending_actions_isolated_per_id() -> None:
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    PENDING_ACTIONS[id_a] = {"action_type": "create_task", "params": {"title": "A"}}
    PENDING_ACTIONS[id_b] = {"action_type": "add_comment", "params": {"message": "B"}}
    assert PENDING_ACTIONS[id_a]["action_type"] == "create_task"
    assert PENDING_ACTIONS[id_b]["action_type"] == "add_comment"


# ---------------------------------------------------------------------------
# Write tool handlers — return pending action, never execute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_task_tool_returns_pending() -> None:
    from app.agent_tools import _tool_create_task  # type: ignore[attr-defined]

    result = await _tool_create_task(project_id=1, title="Тест", responsible_id=5)
    assert result["__pending_action__"] is True
    assert result["action_type"] == "create_task"
    assert result["params"]["title"] == "Тест"
    assert any(f["label"] == "Название" for f in result["display"]["fields"])


@pytest.mark.asyncio
async def test_add_comment_tool_returns_pending() -> None:
    from app.agent_tools import _tool_add_comment  # type: ignore[attr-defined]

    result = await _tool_add_comment(bitrix_task_id=999, message="Проверить смету")
    assert result["__pending_action__"] is True
    assert result["action_type"] == "add_comment"
    assert result["params"]["bitrix_task_id"] == 999


@pytest.mark.asyncio
async def test_assign_user_tool_returns_pending() -> None:
    from app.agent_tools import _tool_assign_user  # type: ignore[attr-defined]

    result = await _tool_assign_user(bitrix_task_id=42, responsible_id=7)
    assert result["__pending_action__"] is True
    assert result["action_type"] == "assign_user"


@pytest.mark.asyncio
async def test_move_task_stage_tool_returns_pending() -> None:
    from app.agent_tools import _tool_move_task_stage  # type: ignore[attr-defined]

    result = await _tool_move_task_stage(bitrix_task_id=10, stage_id=3, stage_name="В работе")
    assert result["__pending_action__"] is True
    assert result["action_type"] == "move_task_stage"
    assert any(f["value"] == "В работе" for f in result["display"]["fields"])


# ---------------------------------------------------------------------------
# execute_pending_action — action_not_found guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_unknown_action_id_returns_error() -> None:
    from app.agent_tools import execute_pending_action

    result = await execute_pending_action("non-existent-uuid")
    assert result == {"error": "action_not_found"}


@pytest.mark.asyncio
async def test_execute_removes_action_from_store() -> None:
    from app.agent_tools import execute_pending_action

    action_id = str(uuid.uuid4())
    # Inject an action that will fail Bitrix (no creds) — we just test it's removed.
    PENDING_ACTIONS[action_id] = {
        "action_type": "add_comment",
        "params": {"bitrix_task_id": 1, "message": "test"},
    }
    # Execute will fail (no real Bitrix connection) but should still pop the action.
    await execute_pending_action(action_id)
    assert action_id not in PENDING_ACTIONS
