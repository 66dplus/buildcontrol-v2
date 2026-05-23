"""Unit tests for write agent tools using DummyClient."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
import pytest
import pytest_asyncio

from config import settings

SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


class DummyClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._next_id = 100

    async def call(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if method == "tasks.task.add":
            task_id = self._next_id; self._next_id += 1
            return {"result": {"task": {"id": task_id}}}
        if method == "task.commentitem.add":
            return {"result": 55}
        if method == "tasks.task.update":
            return {"result": True}
        if method == "task.stages.movetask":
            return {"result": True}
        return {"result": None}

    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass


@pytest_asyncio.fixture
async def db_with_project(tmp_path, monkeypatch):
    db_file = tmp_path / "write_tools.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.executescript(schema)
        await conn.execute(
            "INSERT INTO projects(id, name, is_archived) VALUES(5, 'Тест', 0)"
        )
        await conn.commit()
    yield db_file


@pytest.mark.asyncio
async def test_create_task_calls_bitrix_returns_id(db_with_project):
    import app.agent.tools.create_task  # trigger registration
    from app.agent.tools.create_task import _create_task_tool
    dummy = DummyClient()
    result = await _create_task_tool(
        client=dummy, title="Test task", responsible_id=1,
        group_id=5, deadline="2026-06-01", description="Desc", session_id="s1",
    )
    assert result["task_id"] == 100
    methods = [m for m, _ in dummy.calls]
    assert "tasks.task.add" in methods


@pytest.mark.asyncio
async def test_create_task_is_write_tool():
    import app.agent.tools.create_task
    from app.agent.tools import is_write_tool
    assert is_write_tool("create_task")


@pytest.mark.asyncio
async def test_create_task_writes_audit_log(db_with_project):
    from app.agent.tools.create_task import _create_task_tool
    dummy = DummyClient()
    await _create_task_tool(
        client=dummy, title="Audit test", responsible_id=1,
        group_id=5, session_id="audit-sess",
    )
    async with aiosqlite.connect(str(db_with_project)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM audit_log WHERE tool_name='create_task'"
        ) as cur:
            rows = await cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["session_id"] == "audit-sess"


@pytest.mark.asyncio
async def test_add_comment_calls_bitrix(db_with_project):
    import app.agent.tools.add_comment
    from app.agent.tools.add_comment import _add_comment_tool
    dummy = DummyClient()
    result = await _add_comment_tool(
        client=dummy, task_id=42, message="Test comment", session_id="s1"
    )
    assert result["comment_id"] == 55
    assert any(m == "task.commentitem.add" for m, _ in dummy.calls)


@pytest.mark.asyncio
async def test_add_comment_is_write_tool():
    import app.agent.tools.add_comment
    from app.agent.tools import is_write_tool
    assert is_write_tool("add_comment")


@pytest.mark.asyncio
async def test_assign_user_calls_tasks_update(db_with_project):
    import app.agent.tools.assign_user
    from app.agent.tools.assign_user import _assign_user_tool
    dummy = DummyClient()
    result = await _assign_user_tool(client=dummy, task_id=42, user_id=7, session_id="s1")
    assert result["success"] is True
    params_list = [p for m, p in dummy.calls if m == "tasks.task.update"]
    assert params_list
    assert params_list[0]["fields"]["RESPONSIBLE_ID"] == 7


@pytest.mark.asyncio
async def test_assign_user_is_write_tool():
    import app.agent.tools.assign_user
    from app.agent.tools import is_write_tool
    assert is_write_tool("assign_user")


@pytest.mark.asyncio
async def test_move_task_stage_calls_movetask(db_with_project):
    import app.agent.tools.move_task_stage
    from app.agent.tools.move_task_stage import _move_task_stage_tool
    dummy = DummyClient()
    result = await _move_task_stage_tool(client=dummy, task_id=42, stage_id=99, session_id="s1")
    assert result["success"] is True
    assert any(m == "task.stages.movetask" for m, _ in dummy.calls)


@pytest.mark.asyncio
async def test_move_task_stage_is_write_tool():
    import app.agent.tools.move_task_stage
    from app.agent.tools import is_write_tool
    assert is_write_tool("move_task_stage")


@pytest.mark.asyncio
async def test_dispatch_threads_session_id_into_audit_log(db_with_project, monkeypatch):
    """Regression: dispatch(..., session_id=X) must reach the audit_log row.

    Before this guard was added, `core.run_agent` collected a session_id but
    `dispatch()` dropped it, so every production write-tool audit row landed
    with session_id=NULL. The fix threads it through as `_session_id` in the
    tool's kwargs; this test exercises the full path end-to-end via dispatch().
    """
    import app.agent.tools.add_comment as add_comment_module
    from app.agent.tools import dispatch

    dummy = DummyClient()

    class _BitrixCtx:
        async def __aenter__(self_inner):
            return dummy

        async def __aexit__(self_inner, *_):
            return None

    monkeypatch.setattr(add_comment_module, "BitrixClient", lambda: _BitrixCtx())

    await dispatch(
        "add_comment",
        '{"task_id": 42, "message": "regression"}',
        session_id="sess-abc",
    )

    async with aiosqlite.connect(str(db_with_project)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT session_id FROM audit_log WHERE tool_name='add_comment'"
        ) as cur:
            rows = await cur.fetchall()

    assert len(rows) == 1
    assert rows[0]["session_id"] == "sess-abc"
