"""Agent chat SSE endpoint — uses app.agent.core.run_agent()."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.agent.core import run_agent

router = APIRouter(prefix="", tags=["agent"])
logger = logging.getLogger(__name__)


def _sse_event(data: Any, *, event: str = "chunk") -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


# SSE event name mapping — preserves backward compatibility with test_agent_chat.py
_EVENT_NAMES: dict[str, str] = {
    "text": "chunk",
    "tool_call": "tool_call",
    "tool_result": "tool_result",
    "done": "done",
    "error": "error",
}


@router.post("/api/agent/chat")
async def api_agent_chat(request: Request) -> StreamingResponse:
    """
    Streaming chat endpoint for the SPA AI Assistant.

    Body: ``{"message": "<question>", "session_id": "<optional>", "project_id": <optional int>}``
    Response: ``text/event-stream``
      - ``event: chunk``       data: ``{"type": "text", "content": "..."}`` per text chunk
      - ``event: tool_call``   data: ``{"type": "tool_call", "name": ..., "args": ..., "write": bool}``
      - ``event: tool_result`` data: ``{"type": "tool_result", "name": ..., "result": ...}``
      - ``event: done``        data: ``{"type": "done"}``
      - ``event: error``       data: ``{"type": "error", "content": "..."}``
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    message = (body.get("message") or "").strip()
    session_id = (body.get("session_id") or "").strip() or "anonymous"
    project_id: int | None = body.get("project_id")

    if not message:
        async def _error_stream():
            yield _sse_event({"type": "error", "content": "Empty message"}, event="error")

        return StreamingResponse(
            _error_stream(),
            media_type="text/event-stream",
            status_code=400,
        )

    async def event_stream():
        try:
            async for event in run_agent(message, project_id=project_id, session_id=session_id):
                sse_name = _EVENT_NAMES.get(event.get("type", ""), "chunk")
                yield _sse_event(event, event=sse_name)
        except Exception as exc:
            logger.exception("Agent stream failed: %s", exc)
            yield _sse_event({"type": "error", "content": str(exc)}, event="error")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
