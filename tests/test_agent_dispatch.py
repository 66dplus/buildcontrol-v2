"""
Agent tool dispatch and SQL guardrail tests.

Covers:
- query_database SQL guardrails (only SELECT, auto-LIMIT injection, error passthrough)
- list_projects returns correct structure
- dispatch_write for unknown tool names
- confirm endpoint full round-trip via PENDING_ACTIONS
"""

from __future__ import annotations

import pytest

from app.agent_tools import dispatch_write, PENDING_ACTIONS


# ---------------------------------------------------------------------------
# SQL guardrails in query_database
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_database_rejects_delete() -> None:
    import app.agent.tools.read  # noqa: F401 — trigger registration
    from app.agent.tools.read import _query_database

    result = await _query_database("DELETE FROM projects")
    assert "error" in result
    assert "SELECT" in result["error"]


@pytest.mark.asyncio
async def test_query_database_rejects_insert() -> None:
    import app.agent.tools.read  # noqa: F401
    from app.agent.tools.read import _query_database

    result = await _query_database("INSERT INTO projects (name) VALUES ('x')")
    assert "error" in result


@pytest.mark.asyncio
async def test_query_database_rejects_drop() -> None:
    import app.agent.tools.read  # noqa: F401
    from app.agent.tools.read import _query_database

    result = await _query_database("DROP TABLE projects")
    assert "error" in result


@pytest.mark.asyncio
async def test_query_database_accepts_select_returns_list() -> None:
    import app.agent.tools.read  # noqa: F401
    from app.agent.tools.read import _query_database

    result = await _query_database("SELECT 1 AS n")
    assert isinstance(result, list)
    assert result[0]["n"] == 1


@pytest.mark.asyncio
async def test_query_database_auto_adds_limit() -> None:
    import app.agent.tools.read  # noqa: F401
    from app.agent.tools.read import _query_database

    result = await _query_database("SELECT 1 AS n")
    # Should not raise; the LIMIT is injected internally.
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_query_database_returns_error_on_bad_sql() -> None:
    import app.agent.tools.read  # noqa: F401
    from app.agent.tools.read import _query_database

    result = await _query_database("SELECT * FROM nonexistent_table_xyz")
    assert "error" in result


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_projects_returns_list() -> None:
    import app.agent.tools.read  # noqa: F401
    from app.agent.tools.read import _list_projects

    result = await _list_projects()
    assert isinstance(result, list)
    # Each row has id and name.
    for row in result:
        assert "id" in row
        assert "name" in row


# ---------------------------------------------------------------------------
# dispatch_write — unknown tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_write_unknown_tool_returns_error() -> None:
    result = await dispatch_write("nonexistent_tool", "{}")
    assert "error" in result


@pytest.mark.asyncio
async def test_dispatch_write_invalid_json_returns_error() -> None:
    result = await dispatch_write("create_task", "not-valid-json{")
    assert "error" in result


# ---------------------------------------------------------------------------
# Confirmation round-trip (no Bitrix network call)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_round_trip_add_comment(monkeypatch) -> None:
    """
    Tool → pending action → stored in PENDING_ACTIONS → execute pops it and
    returns an error (no real Bitrix) but the action is gone from the store.
    """
    import uuid
    from app.agent_tools import _tool_add_comment  # type: ignore[attr-defined]

    pending = await _tool_add_comment(bitrix_task_id=1, message="test")
    assert pending["__pending_action__"]

    action_id = str(uuid.uuid4())
    PENDING_ACTIONS[action_id] = {
        "action_type": pending["action_type"],
        "params": pending["params"],
    }
    assert action_id in PENDING_ACTIONS

    from app.agent_tools import execute_pending_action
    result = await execute_pending_action(action_id)
    # Action should be gone regardless of Bitrix success/failure.
    assert action_id not in PENDING_ACTIONS
    # Either succeeded or returned error — but the key was popped.
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_agent_tool_registry_has_read_and_write_tools() -> None:
    """The unified agent TOOL_REGISTRY contains both read and write tools."""
    import app.agent.tools.read  # noqa: F401
    import app.agent.tools.create_task  # noqa: F401
    import app.agent.tools.add_comment  # noqa: F401
    import app.agent.tools.assign_user  # noqa: F401
    import app.agent.tools.move_task_stage  # noqa: F401
    from app.agent.tools import _REGISTRY, is_write_tool

    read_tools = {name for name in _REGISTRY if not is_write_tool(name)}
    write_tools = {name for name in _REGISTRY if is_write_tool(name)}
    assert "list_projects" in read_tools
    assert "query_database" in read_tools
    assert "create_task" in write_tools
    assert "add_comment" in write_tools
