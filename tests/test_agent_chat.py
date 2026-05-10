"""Tests for the SSE chat endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.webhook_handler import app
from config import settings


client = TestClient(app)


def _decode_stream(content: bytes) -> list[str]:
    return content.decode("utf-8").split("\n\n")


def test_chat_demo_mode_when_no_api_key(monkeypatch) -> None:
    """Without OPENROUTER_API_KEY the endpoint returns a canned reply."""
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = client.post("/api/agent/chat", json={"message": "Привет"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    text = r.content.decode("utf-8")
    assert "event: chunk" in text
    assert "event: done" in text
    assert "Демо-режим" in text


def test_chat_rejects_empty_message(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = client.post("/api/agent/chat", json={"message": "   "})
    assert r.status_code == 400
    assert "event: error" in r.content.decode("utf-8")


def test_chat_handles_invalid_json_body(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    # Send raw text instead of JSON
    r = client.post(
        "/api/agent/chat",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_chat_streaming_format_is_valid_sse(monkeypatch) -> None:
    """Each event must start with 'event: ' and contain 'data: ' on the next line."""
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = client.post("/api/agent/chat", json={"message": "test"})
    chunks = [c for c in _decode_stream(r.content) if c.strip()]
    assert len(chunks) > 1, "expected multiple SSE events"
    for c in chunks:
        lines = c.split("\n")
        assert lines[0].startswith("event: "), f"bad event line: {lines[0]!r}"
        assert any(line.startswith("data: ") for line in lines), f"missing data line in {c!r}"
