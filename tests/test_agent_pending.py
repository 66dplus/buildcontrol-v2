"""Tests for app.agent.pending — write-action confirmation gate."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
import pytest
import pytest_asyncio

from config import settings

SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest_asyncio.fixture
async def db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "pending_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.executescript(schema)
        await conn.commit()
    return db_file


@pytest.fixture(autouse=True)
def clear_pending():
    """Each test starts with an empty in-memory store."""
    from app.agent.pending import PENDING_ACTIONS
    PENDING_ACTIONS.clear()
    yield
    PENDING_ACTIONS.clear()


def test_queue_action_stores_and_returns_payload():
    from app.agent.pending import PENDING_ACTIONS, queue_action

    payload = queue_action(
        "create_task",
        {"title": "Покрасить стены", "responsible_id": 7, "group_id": 42, "deadline": "2026-06-01"},
        session_id="sess-1",
    )
    # Returned shape matches frontend PendingAction type.
    assert isinstance(payload["action_id"], str) and len(payload["action_id"]) > 8
    assert "display" in payload
    assert "title" in payload["display"]
    assert "fields" in payload["display"]
    # All fields are {label, value} dicts.
    for f in payload["display"]["fields"]:
        assert set(f.keys()) == {"label", "value"}
    # Action is persisted with full kwargs and session_id.
    stored = PENDING_ACTIONS[payload["action_id"]]
    assert stored["tool_name"] == "create_task"
    assert stored["args"]["title"] == "Покрасить стены"
    assert stored["session_id"] == "sess-1"


def test_queue_action_display_includes_known_tools():
    from app.agent.pending import queue_action

    for name, args, expected_in_title in [
        ("create_task", {"title": "X"}, "X"),
        ("add_comment", {"task_id": 1, "message": "ok"}, "комментарий"),
        ("assign_user", {"task_id": 1, "user_id": 2}, "ответственного"),
        ("move_task_stage", {"task_id": 1, "stage_id": 9}, "этап"),
    ]:
        p = queue_action(name, args, session_id=None)
        assert expected_in_title.lower() in p["display"]["title"].lower()


def test_queue_action_display_fallback_for_unknown_tool():
    from app.agent.pending import queue_action

    p = queue_action("custom_unknown", {"foo": "bar"}, session_id=None)
    assert "custom_unknown" in p["display"]["title"]
    assert p["display"]["fields"] == [{"label": "foo", "value": "bar"}]


@pytest.mark.asyncio
async def test_approve_dispatches_and_clears(db_path, monkeypatch):
    """Approve looks up the action, runs dispatch (with session_id), removes it."""
    from app.agent import pending

    calls: list[tuple[str, str, Any]] = []

    async def fake_dispatch(name: str, args_json: str, *, session_id=None):
        calls.append((name, args_json, session_id))
        return {"task_id": 999}

    monkeypatch.setattr(pending, "dispatch", fake_dispatch)

    payload = pending.queue_action(
        "create_task",
        {"title": "Hi", "group_id": 5},
        session_id="sess-A",
    )
    action_id = payload["action_id"]

    result = await pending.approve(action_id)

    assert result["ok"] is True
    assert result["result"] == {"task_id": 999}
    # Single dispatch with the action's session_id threaded through.
    assert len(calls) == 1
    assert calls[0][0] == "create_task"
    assert calls[0][2] == "sess-A"
    # Pending store no longer contains the action.
    assert action_id not in pending.PENDING_ACTIONS


@pytest.mark.asyncio
async def test_approve_idempotent_on_missing(db_path):
    from app.agent.pending import approve
    result = await approve("does-not-exist")
    assert result == {"ok": False, "error": "action_not_found"}


@pytest.mark.asyncio
async def test_approve_returns_error_when_dispatch_raises(db_path, monkeypatch):
    from app.agent import pending

    async def boom(name, args_json, *, session_id=None):
        raise RuntimeError("bitrix down")

    monkeypatch.setattr(pending, "dispatch", boom)

    payload = pending.queue_action("add_comment", {"task_id": 1, "message": "x"}, session_id="s")
    result = await pending.approve(payload["action_id"])
    assert result == {"ok": False, "error": "bitrix down"}
    # Action is still consumed even on failure — no replay attacks.
    assert payload["action_id"] not in pending.PENDING_ACTIONS


@pytest.mark.asyncio
async def test_reject_writes_audit_row_and_clears(db_path):
    from app.agent import pending

    payload = pending.queue_action(
        "move_task_stage",
        {"task_id": 7, "stage_id": 99},
        session_id="sess-R",
    )
    action_id = payload["action_id"]

    result = await pending.reject(action_id)
    assert result == {"ok": True, "rejected": True}
    assert action_id not in pending.PENDING_ACTIONS

    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT session_id, tool_name, error FROM audit_log "
            "WHERE tool_name='move_task_stage' AND error='rejected_by_user'"
        ) as cur:
            rows = await cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["session_id"] == "sess-R"


@pytest.mark.asyncio
async def test_reject_idempotent_on_missing(db_path):
    from app.agent.pending import reject
    # No prior queue — second click after approve, etc.
    result = await reject("nope")
    assert result == {"ok": True, "rejected": True}
