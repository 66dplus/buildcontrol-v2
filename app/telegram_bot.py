"""
Telegram bot webhook for procurement approval.

Handles inline-keyboard ``callback_query`` events for the four buttons attached
to each request notification:

    pr:approve:<id>   → approve
    pr:reject:<id>    → reject
    pr:comment:<id>   → put the user into "comment mode" (next text message
                        becomes a comment on the request)
    URL link button   → handled by Telegram natively, never reaches us

To bind:
    curl -F "url=$VPS_URL/tg/webhook" \
         -F "secret_token=$TELEGRAM_WEBHOOK_SECRET" \
         https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from bitrix.client import BitrixClient
from app.notifications.telegram import answer_callback_query, send_telegram
from app.purchase_requests import (
    DECISION_APPROVE,
    DECISION_COMMENT,
    DECISION_REJECT,
    SOURCE_TELEGRAM,
    find_request_in_any_project,
    resolve_request,
)
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory: chat_id → request_id awaiting a comment text
_PENDING_COMMENTS: Dict[int, int] = {}


def _verify_secret(header_value: Optional[str]) -> bool:
    expected = settings.telegram_webhook_secret
    if not expected:
        return True  # no secret configured → don't break dev
    return header_value == expected


def _user_label(user: Dict[str, Any]) -> str:
    if user.get("username"):
        return f"@{user['username']}"
    parts = [user.get("first_name") or "", user.get("last_name") or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or f"id:{user.get('id', '?')}"


@router.post("/tg/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> JSONResponse:
    if not _verify_secret(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=401, detail="Invalid secret")

    update = await request.json()

    callback = update.get("callback_query")
    if callback:
        await _handle_callback(callback)
        return JSONResponse(content={"ok": True})

    message = update.get("message")
    if message:
        await _handle_message(message)
        return JSONResponse(content={"ok": True})

    return JSONResponse(content={"ok": True})


async def _handle_callback(callback: Dict[str, Any]) -> None:
    cb_id = callback.get("id")
    data = callback.get("data") or ""
    user = callback.get("from") or {}
    chat = (callback.get("message") or {}).get("chat") or {}
    chat_id = chat.get("id")
    actor = _user_label(user)

    if not data.startswith("pr:"):
        if cb_id:
            await answer_callback_query(cb_id, "Неизвестное действие")
        return

    parts = data.split(":")
    if len(parts) != 3:
        if cb_id:
            await answer_callback_query(cb_id, "Некорректные данные")
        return
    _, action, raw_id = parts
    try:
        request_id = int(raw_id)
    except ValueError:
        if cb_id:
            await answer_callback_query(cb_id, "Некорректный ID")
        return

    decision_map = {
        "approve": DECISION_APPROVE,
        "reject": DECISION_REJECT,
        "comment": DECISION_COMMENT,
    }
    decision = decision_map.get(action)
    if decision is None:
        if cb_id:
            await answer_callback_query(cb_id, "Неизвестное действие")
        return

    if decision == DECISION_COMMENT:
        if chat_id is not None:
            _PENDING_COMMENTS[int(chat_id)] = request_id
        if cb_id:
            await answer_callback_query(cb_id, "Напишите следующим сообщением свой комментарий")
        try:
            await send_telegram(
                f"💬 Введите комментарий к заявке №{request_id} следующим сообщением.",
                chat_id=str(chat_id) if chat_id is not None else None,
            )
        except Exception as e:
            logger.warning(f"Telegram comment prompt failed: {e}")
        return

    async with BitrixClient() as client:
        located = await find_request_in_any_project(client, request_id)
        if not located:
            if cb_id:
                await answer_callback_query(cb_id, "Заявка не найдена", show_alert=True)
            return
        project_id, *_ = located
        result = await resolve_request(
            client, project_id, request_id,
            decision=decision, actor=actor, source=SOURCE_TELEGRAM,
        )

    if cb_id:
        if result.get("already_resolved"):
            await answer_callback_query(cb_id, f"Заявка уже {result.get('status')}", show_alert=True)
        else:
            tag = "✅ Подтверждено" if decision == DECISION_APPROVE else "❌ Отклонено"
            await answer_callback_query(cb_id, tag)


async def _handle_message(message: Dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    user = message.get("from") or {}
    actor = _user_label(user)

    if chat_id is None or not text:
        return

    # Only process messages from authorised chat IDs
    from config import settings
    if int(chat_id) not in settings.telegram_director_chat_ids:
        return

    pending_request_id = _PENDING_COMMENTS.pop(int(chat_id), None)
    if pending_request_id is None:
        # Free-form text → route to AI director agent
        from app.telegram_agent import handle_director_query
        await handle_director_query(int(chat_id), text)
        return

    async with BitrixClient() as client:
        located = await find_request_in_any_project(client, pending_request_id)
        if not located:
            await send_telegram(
                f"⚠ Заявка №{pending_request_id} не найдена — комментарий не сохранён.",
                chat_id=str(chat_id),
            )
            return
        project_id, *_ = located
        await resolve_request(
            client, project_id, pending_request_id,
            decision=DECISION_COMMENT, actor=actor, source=SOURCE_TELEGRAM, comment=text,
        )
