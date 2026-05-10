"""Agent chat SSE streaming endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["agent"])


@router.post("/api/agent/chat")
async def api_agent_chat(request: Request) -> StreamingResponse:
    """
    Streaming chat endpoint for the SPA AI Assistant.

    Body: ``{"message": "<question>", "session_id": "<optional>"}``
    Response: ``text/event-stream`` with the following events:
      - ``event: chunk``  data: ``{"text": "..."}`` per token delta
      - ``event: done``   data: ``{}`` when the reply is complete
      - ``event: error``  data: ``{"message": "..."}`` on failure

    Requires OPENROUTER_API_KEY in env; without it the endpoint returns a
    canned demo reply so the UI is testable.
    """
    from app.agent_chat import stream_director_query, sse_event

    try:
        body = await request.json()
    except Exception:
        body = {}
    message = (body.get("message") or "").strip()
    if not message:
        return StreamingResponse(
            iter([sse_event({"message": "Empty message"}, event="error")]),
            media_type="text/event-stream",
            status_code=400,
        )

    async def event_stream():
        try:
            async for item in stream_director_query(message):
                if isinstance(item, dict) and "__action__" in item:
                    yield sse_event(item["__action__"], event="action")
                    yield sse_event({}, event="done")
                    return
                yield sse_event({"text": item})
            yield sse_event({}, event="done")
        except Exception as exc:
            logger.exception("Agent stream failed: %s", exc)
            yield sse_event({"message": str(exc)}, event="error")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        },
    )
