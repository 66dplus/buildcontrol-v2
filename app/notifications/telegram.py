"""
Low-level Telegram message sender for BuildControl notifications.

All notification calls are fire-and-forget — failures are logged,
never raised to the caller. The main report/buyer-report flow must
never break because Telegram is unreachable.
"""

import logging
from typing import Any, Dict, List, Optional, Union

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Telegram Bot API base URL
_TG_API = "https://api.telegram.org/bot{token}/sendMessage"
_TG_ANSWER_CALLBACK = "https://api.telegram.org/bot{token}/answerCallbackQuery"
_TG_EDIT_MESSAGE = "https://api.telegram.org/bot{token}/editMessageText"
_TG_EDIT_REPLY_MARKUP = "https://api.telegram.org/bot{token}/editMessageReplyMarkup"

# Telegram message limit is 4096 chars; we truncate to be safe
_MAX_MESSAGE_LEN = 4000


async def send_telegram(
    message: str,
    parse_mode: str = "HTML",
    chat_id: Optional[str] = None,
) -> bool:
    """
    Send a message via Telegram Bot API.

    Args:
        message: Text to send (HTML or plain).
        parse_mode: "HTML" or "MarkdownV2".
        chat_id: Override chat ID (defaults to settings.telegram_chat_id).

    Returns:
        True if sent successfully, False otherwise.
    """
    if not settings.notifications_enabled:
        logger.debug("Notifications disabled, skipping Telegram message")
        return False

    token = settings.telegram_bot_token
    target_chat = chat_id or settings.telegram_chat_id

    if not token or not target_chat:
        logger.warning("Telegram not configured: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False

    # Truncate if too long
    if len(message) > _MAX_MESSAGE_LEN:
        message = message[:_MAX_MESSAGE_LEN] + "\n\n... (сообщение обрезано)"

    url = _TG_API.format(token=token)
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": parse_mode,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Telegram message sent successfully")
                return True
            else:
                logger.warning(f"Telegram API error: {resp.status_code} — {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


async def send_telegram_with_buttons(
    message: str,
    keyboard: List[List[Dict[str, Any]]],
    parse_mode: str = "HTML",
    chat_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Send a message with an inline keyboard. Returns the Telegram ``message`` object on
    success (so callers can capture ``message_id`` for later edits), or ``None`` on failure.

    ``keyboard`` is a list of rows; each row is a list of button dicts. Each dict
    must include ``text`` and exactly one of ``callback_data`` or ``url``.
    """
    if not settings.notifications_enabled:
        logger.debug("Notifications disabled, skipping Telegram message")
        return None

    token = settings.telegram_bot_token
    target_chat = chat_id or settings.telegram_approver_chat_id or settings.telegram_chat_id
    if not token or not target_chat:
        logger.warning("Telegram not configured: missing TELEGRAM_BOT_TOKEN or chat id")
        return None

    if len(message) > _MAX_MESSAGE_LEN:
        message = message[:_MAX_MESSAGE_LEN] + "\n\n... (сообщение обрезано)"

    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": parse_mode,
        "reply_markup": {"inline_keyboard": keyboard},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_TG_API.format(token=token), json=payload)
            if resp.status_code != 200:
                logger.warning(f"Telegram API error: {resp.status_code} — {resp.text}")
                return None
            data = resp.json()
            if not data.get("ok"):
                logger.warning(f"Telegram returned not-ok: {data}")
                return None
            return data.get("result")
    except Exception as e:
        logger.error(f"Telegram send_with_buttons failed: {e}")
        return None


async def edit_message_text(
    chat_id: Union[int, str],
    message_id: int,
    text: str,
    parse_mode: str = "HTML",
    drop_buttons: bool = True,
) -> bool:
    """
    Replace the text of a previously sent Telegram message in place.
    By default also strips inline buttons so the resolved request can no longer
    be acted on.
    """
    token = settings.telegram_bot_token
    if not token:
        return False
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[:_MAX_MESSAGE_LEN - 20] + "\n... (обрезано)"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if drop_buttons:
        payload["reply_markup"] = {"inline_keyboard": []}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_TG_EDIT_MESSAGE.format(token=token), json=payload)
            if resp.status_code != 200:
                logger.warning(f"Telegram editMessageText failed: {resp.status_code} — {resp.text}")
                return False
            return bool(resp.json().get("ok"))
    except Exception as e:
        logger.warning(f"Telegram edit_message_text exception: {e}")
        return False


async def answer_callback_query(
    callback_query_id: str,
    text: Optional[str] = None,
    show_alert: bool = False,
) -> bool:
    """Acknowledge a Telegram callback_query so the user's tap is confirmed."""
    token = settings.telegram_bot_token
    if not token:
        return False
    payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_TG_ANSWER_CALLBACK.format(token=token), json=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Telegram answer_callback_query failed: {e}")
        return False
