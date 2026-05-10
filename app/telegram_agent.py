"""Telegram adapter for the BuildControl director agent.

handle_director_query() is the single entry point called by the Telegram
webhook. It delegates to app.agent.core.run_agent() and collects all text
events into one Telegram message.

Write-tool events (create_task, add_comment, etc.) execute immediately —
there is no UI confirmation in Telegram. The agent's natural-language reply
describes what was done.
"""
from __future__ import annotations

import logging

from app.agent.core import run_agent
from app.notifications.telegram import send_telegram

logger = logging.getLogger(__name__)


async def _send_telegram_message(chat_id: int, text: str) -> None:
    """Wrapper around send_telegram — kept separate so tests can patch it."""
    await send_telegram(text, chat_id=str(chat_id))


async def handle_director_query(chat_id: int, text: str) -> None:
    """Run agent for one message and send the combined reply to Telegram."""
    parts: list[str] = []
    try:
        async for event in run_agent(text, project_id=None, session_id=f"tg-{chat_id}"):
            if event["type"] == "text":
                parts.append(event["content"])
            elif event["type"] == "error":
                parts.append(f"Ошибка: {event['content']}")
    except Exception as exc:
        logger.exception("Telegram agent error for chat %s: %s", chat_id, exc)
        parts.append(f"Внутренняя ошибка: {exc}")

    reply = "".join(parts).strip() or "Нет ответа."
    await _send_telegram_message(chat_id, reply)
