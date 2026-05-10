"""Agent LLM loop — async generator yielding typed SSE event dicts.

Event types:
    {"type": "text", "content": str}
    {"type": "tool_call", "name": str, "args": dict, "write": bool}
    {"type": "tool_result", "name": str, "result": Any}
    {"type": "done"}
    {"type": "error", "content": str}
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from openai import AsyncOpenAI

# Import all tool modules to trigger registration
import app.agent.tools.read  # noqa: F401
import app.agent.tools.create_task  # noqa: F401
import app.agent.tools.add_comment  # noqa: F401
import app.agent.tools.assign_user  # noqa: F401
import app.agent.tools.move_task_stage  # noqa: F401
from app.agent.tools import dispatch, get_openai_tools, is_write_tool

from config import settings
from db.schema_docs import SCHEMA_DOCS

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 8

_DEMO_REPLY = (
    "Демо-режим: ключ OPENROUTER_API_KEY не задан в .env. "
    "Чтобы получить реальные ответы агента, добавьте ключ и перезапустите backend."
)

SYSTEM_PROMPT = f"""Ты ассистент директора строительной компании.
Отвечай ТОЛЬКО на русском языке.
{SCHEMA_DOCS}
"""


async def run_agent(
    message: str,
    project_id: Optional[int],
    session_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Yield typed SSE event dicts for one user message."""
    if not settings.openrouter_api_key:
        for word in _DEMO_REPLY.split(" "):
            yield {"type": "text", "content": word + " "}
        yield {"type": "done"}
        return

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    tools = get_openai_tools()
    messages: List[Dict[str, Any]] = [{"role": "user", "content": message}]

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
                    name = call.function.name
                    args_json = call.function.arguments
                    args = json.loads(args_json) if args_json else {}
                    yield {"type": "tool_call", "name": name, "args": args,
                           "write": is_write_tool(name)}
                    result = await dispatch(name, args_json)
                    yield {"type": "tool_result", "name": name, "result": result}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
            else:
                text = (msg.content or "").strip()
                if text:
                    yield {"type": "text", "content": text}
                yield {"type": "done"}
                return

        yield {"type": "text", "content": "Слишком много шагов. Уточните вопрос."}
        yield {"type": "done"}

    except Exception as exc:
        logger.exception("Agent core error: %s", exc)
        yield {"type": "error", "content": str(exc)}
