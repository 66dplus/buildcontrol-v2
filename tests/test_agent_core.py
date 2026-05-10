"""Tests for app.agent.core.run_agent() SSE event generator."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from config import settings

SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest_asyncio.fixture
async def db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "core_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(str(db_file)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.executescript(schema)
        await conn.commit()
    return db_file


async def _collect(gen: AsyncIterator) -> list:
    events = []
    async for ev in gen:
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_run_agent_demo_mode_yields_text_and_done(db_path, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    from app.agent.core import run_agent
    events = await _collect(run_agent("Hello", project_id=None, session_id="s1"))
    types = [e["type"] for e in events]
    assert "text" in types
    assert "done" in types
    assert "error" not in types


@pytest.mark.asyncio
async def test_run_agent_all_events_have_type(db_path, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    from app.agent.core import run_agent
    events = await _collect(run_agent("Test", project_id=None, session_id="s2"))
    for ev in events:
        assert "type" in ev


@pytest.mark.asyncio
async def test_run_agent_demo_text_contains_demo_string(db_path, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    from app.agent.core import run_agent
    events = await _collect(run_agent("Hi", project_id=None, session_id="s3"))
    text = "".join(e["content"] for e in events if e["type"] == "text")
    assert "Демо-режим" in text


@pytest.mark.asyncio
async def test_run_agent_tool_call_yields_tool_events(db_path, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")

    tc = MagicMock()
    tc.function.name = "list_projects"
    tc.function.arguments = "{}"
    tc.id = "call_abc"

    msg1 = MagicMock()
    msg1.tool_calls = [tc]
    msg1.model_dump.return_value = {"role": "assistant", "tool_calls": []}

    msg2 = MagicMock()
    msg2.tool_calls = None
    msg2.content = "Активных проектов нет."

    c1 = MagicMock(); c1.finish_reason = "tool_calls"; c1.message = msg1
    c2 = MagicMock(); c2.finish_reason = "stop"; c2.message = msg2

    r1 = MagicMock(); r1.choices = [c1]
    r2 = MagicMock(); r2.choices = [c2]

    with patch("app.agent.core.AsyncOpenAI") as MockOAI:
        MockOAI.return_value.chat.completions.create = AsyncMock(side_effect=[r1, r2])
        from app.agent.core import run_agent
        import app.agent.tools.read  # ensure list_projects registered
        events = await _collect(run_agent("List", project_id=None, session_id="s4"))

    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert "text" in types
    assert "done" in types

    tc_event = next(e for e in events if e["type"] == "tool_call")
    assert tc_event["name"] == "list_projects"
    assert "write" in tc_event
    assert tc_event["write"] is False


@pytest.mark.asyncio
async def test_run_agent_error_on_llm_exception(db_path, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")
    with patch("app.agent.core.AsyncOpenAI") as MockOAI:
        MockOAI.return_value.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("LLM exploded")
        )
        from app.agent.core import run_agent
        events = await _collect(run_agent("Crash", project_id=None, session_id="s5"))
    assert any(e["type"] == "error" for e in events)
