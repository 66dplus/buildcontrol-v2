"""Pending write-action store for the agent confirmation gate.

Write tools never execute directly from the agent loop. Instead, the loop
yields an ``action`` SSE event carrying an ``action_id`` and a display
payload; the SPA renders a ConfirmActionCard and POSTs to
``/api/agent/confirm`` to approve/reject. Only on approval does
``dispatch()`` run the real Bitrix call (with full audit-log threading
from Bucket A).

The store is in-memory and per-process — pending actions vanish on
restart. That's acceptable for short-lived approvals; if the server
restarts mid-decision the user re-asks.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

from app.agent.audit import write_audit_log
from app.agent.tools import dispatch

logger = logging.getLogger(__name__)

PENDING_ACTIONS: Dict[str, Dict[str, Any]] = {}


def queue_action(
    tool_name: str,
    args: Dict[str, Any],
    session_id: Optional[str],
) -> Dict[str, Any]:
    """Store a pending action; return the SSE ``action`` event payload.

    Returned shape matches the frontend ``PendingAction`` type:
    ``{action_id, display: {title, fields: [{label, value}]}}``.
    """
    action_id = str(uuid.uuid4())
    PENDING_ACTIONS[action_id] = {
        "tool_name": tool_name,
        "args": args,
        "session_id": session_id,
    }
    return {"action_id": action_id, "display": _build_display(tool_name, args)}


def _build_display(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Render a confirmation card from raw tool kwargs."""
    if tool_name == "create_task":
        title = str(args.get("title", "")) or "(без названия)"
        fields = [{"label": "Название", "value": title}]
        if args.get("responsible_id"):
            fields.append({"label": "Ответственный (ID)", "value": str(args["responsible_id"])})
        if args.get("group_id"):
            fields.append({"label": "Проект (group_id)", "value": str(args["group_id"])})
        if args.get("deadline"):
            fields.append({"label": "Срок", "value": str(args["deadline"])})
        if args.get("description"):
            fields.append({"label": "Описание", "value": str(args["description"])[:120]})
        return {"title": f"Создать задачу: «{title}»", "fields": fields}

    if tool_name == "add_comment":
        return {
            "title": "Добавить комментарий к задаче",
            "fields": [
                {"label": "Задача (ID)", "value": str(args.get("task_id", ""))},
                {"label": "Комментарий", "value": str(args.get("message", ""))[:120]},
            ],
        }

    if tool_name == "assign_user":
        return {
            "title": "Переназначить ответственного",
            "fields": [
                {"label": "Задача (ID)", "value": str(args.get("task_id", ""))},
                {"label": "Новый ответственный (ID)", "value": str(args.get("user_id", ""))},
            ],
        }

    if tool_name == "move_task_stage":
        return {
            "title": "Переместить задачу на этап",
            "fields": [
                {"label": "Задача (ID)", "value": str(args.get("task_id", ""))},
                {"label": "Этап (ID)", "value": str(args.get("stage_id", ""))},
            ],
        }

    return {
        "title": f"Выполнить: {tool_name}",
        "fields": [{"label": k, "value": str(v)[:120]} for k, v in args.items()],
    }


async def approve(action_id: str) -> Dict[str, Any]:
    """Execute the queued action via dispatch. Audit log handled inside dispatch.

    Idempotent: second call with the same id (after the action was already
    consumed) returns ``action_not_found`` rather than re-running.
    """
    action = PENDING_ACTIONS.pop(action_id, None)
    if action is None:
        return {"ok": False, "error": "action_not_found"}
    try:
        result = await dispatch(
            action["tool_name"],
            json.dumps(action["args"], ensure_ascii=False),
            session_id=action["session_id"],
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        logger.exception("approve(%s) raised: %s", action_id, exc)
        return {"ok": False, "error": str(exc)}


async def reject(action_id: str) -> Dict[str, Any]:
    """Drop the queued action and record the rejection in audit_log."""
    action = PENDING_ACTIONS.pop(action_id, None)
    if action is None:
        return {"ok": True, "rejected": True}
    await write_audit_log(
        session_id=action.get("session_id"),
        tool_name=action["tool_name"],
        args=action["args"],
        result=None,
        error="rejected_by_user",
    )
    return {"ok": True, "rejected": True}
