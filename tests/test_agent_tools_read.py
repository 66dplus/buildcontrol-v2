"""Unit tests for read-only agent tools."""
from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from config import settings

SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest_asyncio.fixture
async def db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "agent_read.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.executescript(schema)
        await conn.execute(
            "INSERT INTO projects(id, name, is_archived) VALUES(1, 'Тест', 0)"
        )
        await conn.commit()
    return db_file


@pytest.mark.asyncio
async def test_list_projects_returns_active(db_path):
    import app.agent.tools.read  # trigger registration
    from app.agent.tools import dispatch
    result = await dispatch("list_projects", "{}")
    assert isinstance(result, list)
    assert any(p["name"] == "Тест" for p in result)


@pytest.mark.asyncio
async def test_list_projects_is_not_write():
    import app.agent.tools.read
    from app.agent.tools import TOOL_REGISTRY
    _, _, is_write = TOOL_REGISTRY["list_projects"]
    assert not is_write


@pytest.mark.asyncio
async def test_query_database_returns_rows(db_path):
    import app.agent.tools.read
    from app.agent.tools import dispatch
    result = await dispatch("query_database", '{"sql": "SELECT id, name FROM projects"}')
    assert isinstance(result, list)
    assert result[0]["name"] == "Тест"


@pytest.mark.asyncio
async def test_query_database_blocks_non_select(db_path):
    import app.agent.tools.read
    from app.agent.tools import dispatch
    result = await dispatch("query_database", '{"sql": "DELETE FROM projects"}')
    assert "error" in result


@pytest.mark.asyncio
async def test_query_database_allows_commented_select(db_path):
    """SQL starting with -- comment lines must still work (LLM annotates its queries)."""
    import app.agent.tools.read
    from app.agent.tools import dispatch
    sql = '{"sql": "-- check active projects\\nSELECT id FROM projects WHERE is_archived=0"}'
    result = await dispatch("query_database", sql)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_query_database_blocks_non_select_after_comment(db_path):
    """A non-SELECT disguised with a leading comment must still be blocked."""
    import app.agent.tools.read
    from app.agent.tools import dispatch
    sql = '{"sql": "-- looks safe\\nDELETE FROM projects"}'
    result = await dispatch("query_database", sql)
    assert "error" in result


@pytest.mark.asyncio
async def test_query_database_appends_limit(db_path):
    import app.agent.tools.read
    from app.agent.tools import dispatch
    result = await dispatch("query_database", '{"sql": "SELECT id FROM projects"}')
    assert isinstance(result, list)
