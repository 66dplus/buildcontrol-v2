"""Verify telegram_agent adapts to core.run_agent() and stays importable."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from config import settings

SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest_asyncio.fixture
async def db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "tg_adapter.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.executescript(schema)
        await conn.commit()
    return db_file


def test_handle_director_query_is_importable():
    from app.telegram_agent import handle_director_query
    import inspect
    assert inspect.iscoroutinefunction(handle_director_query)


@pytest.mark.asyncio
async def test_handle_director_query_demo_mode_sends_reply(db_path, monkeypatch):
    """In demo mode (no API key), handle_director_query should call the Telegram send function."""
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    sent: list[str] = []

    async def _fake_send(chat_id: int, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("app.telegram_agent._send_telegram_message", _fake_send)
    from app.telegram_agent import handle_director_query
    await handle_director_query(chat_id=123, text="Привет")
    assert len(sent) == 1
    assert "Демо-режим" in sent[0]
