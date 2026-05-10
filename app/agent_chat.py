"""
SSE streaming wrapper around telegram_agent.handle_director_query.

The Telegram bot waits for the full reply before sending it to a chat. The web
SPA wants progressive output, so this module exposes ``stream_director_query``
which yields tokens as they arrive from OpenRouter.

Tool-call rounds are NOT streamed — we run them with stream=False because the
intermediate JSON has no value for the user. Only the final assistant message
streams.

Demo fallback: when OPENROUTER_API_KEY is not set, the generator yields a
canned reply so the UI is testable without API credentials.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List

from openai import AsyncOpenAI

from app.telegram_agent import (
    SYSTEM_PROMPT,
    TOOL_REGISTRY,
    _MAX_TOOL_ROUNDS,
    _dispatch,
)
from config import settings

logger = logging.getLogger(__name__)


_DEMO_REPLY = (
    "Демо-режим: ключ OPENROUTER_API_KEY не задан в .env. "
    "Чтобы получить реальные ответы агента, добавьте ключ и перезапустите backend.\n\n"
    "Пример вопроса: «Какие проекты в перерасходе?» — агент сделает SQL-запрос "
    "к budget_phases, отфильтрует по variance > 15% и вернёт список с суммами."
)


async def _stream_demo() -> AsyncIterator[str]:
    """Yield the demo reply word-by-word so the UI animation looks real."""
    for word in _DEMO_REPLY.split(" "):
        yield word + " "


async def stream_director_query(text: str) -> AsyncIterator[str]:
    """
    Run the agent tool-loop, then stream the final reply token-by-token.

    Yields plain text deltas (not SSE-wrapped). The endpoint layer wraps each
    delta into ``data: {...}\\n\\n``.
    """
    if not settings.openrouter_api_key:
        async for chunk in _stream_demo():
            yield chunk
        return

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    tools: List[Dict[str, Any]] = [schema for schema, _ in TOOL_REGISTRY.values()]
    messages: List[Dict[str, Any]] = [{"role": "user", "content": text}]

    try:
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(
                model=settings.openrouter_model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                tools=tools,
                tool_choice="auto",
            )
            choice = response.choices[0]
            msg = choice.message

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                messages.append(msg.model_dump(exclude_unset=True))
                for call in msg.tool_calls:
                    result = await _dispatch(call.function.name, call.function.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                continue

            # Final round — stream the assistant reply.
            stream = await client.chat.completions.create(
                model=settings.openrouter_model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                stream=True,
            )
            async for delta in stream:
                token = delta.choices[0].delta.content if delta.choices else None
                if token:
                    yield token
            return

        yield "Не удалось получить ответ — слишком много шагов. Попробуйте уточнить вопрос."

    except Exception as exc:
        logger.exception("Agent chat error: %s", exc)
        yield f"Произошла ошибка при обработке запроса: {exc}"


def sse_event(data: Any, *, event: str = "chunk") -> bytes:
    """Encode a single SSE event. Newlines in data are escaped per the spec."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
