"""Tests for the audit log writer."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest_asyncio.fixture
async def db():
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await conn.executescript(schema)
        await conn.commit()
        yield conn


@pytest.mark.asyncio
async def test_write_audit_log_conn_inserts_row(db):
    from app.agent.audit import write_audit_log_conn
    await write_audit_log_conn(
        db,
        session_id="s1",
        tool_name="list_projects",
        args={"foo": "bar"},
        result={"id": 1},
        error=None,
    )
    async with db.execute("SELECT * FROM audit_log") as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "list_projects"
    assert json.loads(rows[0]["args_json"]) == {"foo": "bar"}
    assert json.loads(rows[0]["result_json"]) == {"id": 1}
    assert rows[0]["error"] is None


@pytest.mark.asyncio
async def test_write_audit_log_conn_records_error(db):
    from app.agent.audit import write_audit_log_conn
    await write_audit_log_conn(
        db,
        session_id="s2",
        tool_name="create_task",
        args={"title": "X"},
        result=None,
        error="Bitrix unreachable",
    )
    async with db.execute("SELECT error FROM audit_log WHERE session_id='s2'") as cur:
        row = await cur.fetchone()
    assert row["error"] == "Bitrix unreachable"
