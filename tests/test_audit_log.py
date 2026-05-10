"""Tests that audit_log table exists and accepts writes."""
from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest

SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest.fixture
def _db():
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    async def _setup():
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row
        await conn.executescript(schema)
        await conn.commit()
        return conn

    return asyncio.get_event_loop().run_until_complete(_setup())


def test_audit_log_table_exists(_db):
    async def _check():
        async with _db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None

    asyncio.get_event_loop().run_until_complete(_check())


def test_audit_log_accepts_write(_db):
    async def _write():
        await _db.execute(
            """INSERT INTO audit_log
               (timestamp, session_id, tool_name, args_json, result_json, error)
               VALUES (datetime('now'), 'sess-1', 'create_task',
                       '{"title": "Test"}', '{"task_id": 42}', NULL)"""
        )
        await _db.commit()
        async with _db.execute("SELECT COUNT(*) FROM audit_log") as cur:
            row = await cur.fetchone()
        assert row[0] == 1

    asyncio.get_event_loop().run_until_complete(_write())
