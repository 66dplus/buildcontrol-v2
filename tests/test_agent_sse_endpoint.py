"""Integration tests for POST /api/agent/chat using core.run_agent()."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.webhook_handler import app
from config import settings

_client = TestClient(app)


def test_sse_endpoint_demo_mode_backward_compat(monkeypatch):
    """Ensure 'event: chunk' and 'event: done' are preserved for frontend compat."""
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = _client.post("/api/agent/chat", json={"message": "Привет"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    text = r.content.decode("utf-8")
    assert "event: chunk" in text
    assert "event: done" in text
    assert "Демо-режим" in text


def test_sse_events_have_type_field_in_data(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = _client.post("/api/agent/chat", json={"message": "Привет"})
    text = r.content.decode("utf-8")
    for line in text.split("\n"):
        if line.startswith("data: "):
            payload = json.loads(line[6:])
            assert "type" in payload


def test_empty_message_returns_400(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = _client.post("/api/agent/chat", json={"message": "   "})
    assert r.status_code == 400
