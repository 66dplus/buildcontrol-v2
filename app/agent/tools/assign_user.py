"""Write tool: assign_user."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.agent.audit import write_audit_log
from app.agent.tools import _register
from bitrix.client import BitrixClient

logger = logging.getLogger(__name__)


async def _assign_user_tool(
    *, client: Any, task_id: int, user_id: int, session_id: Optional[str] = None,
) -> dict[str, Any]:
    args = {"task_id": task_id, "user_id": user_id}
    try:
        await client.call(
            "tasks.task.update",
            {"taskId": task_id, "fields": {"RESPONSIBLE_ID": user_id}},
        )
        result = {"success": True}
        await write_audit_log(session_id=session_id, tool_name="assign_user",
                              args=args, result=result, error=None)
        return result
    except Exception as exc:
        await write_audit_log(session_id=session_id, tool_name="assign_user",
                              args=args, result=None, error=str(exc))
        raise


@_register({
    "type": "function",
    "function": {
        "name": "assign_user",
        "description": "Assign a Bitrix24 task to a user (change RESPONSIBLE_ID).",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Bitrix task ID"},
                "user_id": {"type": "integer", "description": "Bitrix user ID to assign"},
            },
            "required": ["task_id", "user_id"],
        },
    },
    "write": True,
})
async def _assign_user_registered(
    task_id: int, user_id: int,
    _session_id: Optional[str] = None, **_: Any,
) -> dict[str, Any]:
    async with BitrixClient() as client:
        return await _assign_user_tool(
            client=client, task_id=task_id, user_id=user_id,
            session_id=_session_id,
        )
