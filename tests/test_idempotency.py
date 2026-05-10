"""Tests for the idempotency cache helpers in db.repo."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import aiosqlite
import pytest
import pytest_asyncio

from db import repo


SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[aiosqlite.Connection]:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(":memory:") as c:
        c.row_factory = aiosqlite.Row
        await c.executescript(schema)
        await c.commit()
        yield c


@pytest.mark.asyncio
async def test_miss_returns_none(conn: aiosqlite.Connection) -> None:
    assert await repo.get_idempotent_response(conn, "never-seen") is None


@pytest.mark.asyncio
async def test_empty_key_is_noop(conn: aiosqlite.Connection) -> None:
    # Empty key: store is a no-op, get returns None.
    await repo.store_idempotent_response(conn, "", {"x": 1})
    assert await repo.get_idempotent_response(conn, "") is None


@pytest.mark.asyncio
async def test_round_trip(conn: aiosqlite.Connection) -> None:
    body = {"success": True, "link": "https://example.com/group/1/lists/"}
    await repo.store_idempotent_response(conn, "k1", body)

    cached = await repo.get_idempotent_response(conn, "k1")
    assert cached is not None
    assert cached["status_code"] == 200
    assert cached["body"] == body


@pytest.mark.asyncio
async def test_status_code_is_persisted(conn: aiosqlite.Connection) -> None:
    await repo.store_idempotent_response(conn, "k2", {"ok": False}, status_code=400)
    cached = await repo.get_idempotent_response(conn, "k2")
    assert cached is not None
    assert cached["status_code"] == 400


@pytest.mark.asyncio
async def test_second_store_is_ignored(conn: aiosqlite.Connection) -> None:
    # Same key again must not overwrite — first response wins (the whole point
    # of the cache: the SECOND submit must see the FIRST response).
    await repo.store_idempotent_response(conn, "k3", {"v": "first"})
    await repo.store_idempotent_response(conn, "k3", {"v": "second"})
    cached = await repo.get_idempotent_response(conn, "k3")
    assert cached is not None
    assert cached["body"] == {"v": "first"}


@pytest.mark.asyncio
async def test_ttl_eviction(conn: aiosqlite.Connection) -> None:
    # Store at t=0, read 25h later (now_ts = 25*3600). Entry is evicted.
    await repo.store_idempotent_response(conn, "old", {"v": 1}, now_ts=0)
    cached = await repo.get_idempotent_response(conn, "old", now_ts=25 * 3600)
    assert cached is None

    # Within TTL — still there.
    await repo.store_idempotent_response(conn, "fresh", {"v": 2}, now_ts=0)
    cached = await repo.get_idempotent_response(conn, "fresh", now_ts=23 * 3600)
    assert cached is not None
    assert cached["body"] == {"v": 2}
