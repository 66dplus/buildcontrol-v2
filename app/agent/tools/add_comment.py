"""Write tool: add_comment."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.agent.audit import write_audit_log
from app.agent.tools import _register
from bitrix.client import BitrixClient
from bitrix.methods import tasks as tasks_methods

logger = logging.getLogger(__name__)


async def _add_comment_tool(
    *, client: Any, task_id: int, message: str, session_id: Optional[str] = None,
) -> dict[str, Any]:
    args = {"task_id": task_id, "message": message}
    try:
        comment_id = await tasks_methods.add_task_comment(client, task_id, message)
        result = {"comment_id": comment_id}
        await write_audit_log(session_id=session_id, tool_name="add_comment",
                              args=args, result=result, error=None)
        return result
    except Exception as exc:
        await write_audit_log(session_id=session_id, tool_name="add_comment",
                              args=args, result=None, error=str(exc))
        raise


@_register({
    "type": "function",
    "function": {
        "name": "add_comment",
        "description": "Add a comment to an existing Bitrix24 task.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Bitrix task ID"},
                "message": {"type": "string", "description": "Comment text (Russian ok)"},
            },
            "required": ["task_id", "message"],
        },
    },
    "write": True,
})
async def _add_comment_registered(
    task_id: int, message: str,
    _session_id: Optional[str] = None, **_: Any,
) -> dict[str, Any]:
    async with BitrixClient() as client:
        return await _add_comment_tool(
            client=client, task_id=task_id, message=message,
            session_id=_session_id,
        )
