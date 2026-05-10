"""Write tool: move_task_stage."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.agent.audit import write_audit_log
from app.agent.tools import _register
from bitrix.client import BitrixClient
from bitrix.methods import tasks as tasks_methods

logger = logging.getLogger(__name__)


async def _move_task_stage_tool(
    *, client: Any, task_id: int, stage_id: int, session_id: Optional[str] = None,
) -> dict[str, Any]:
    args = {"task_id": task_id, "stage_id": stage_id}
    try:
        await tasks_methods.move_task_to_stage(client, task_id, stage_id)
        result = {"success": True}
        await write_audit_log(session_id=session_id, tool_name="move_task_stage",
                              args=args, result=result, error=None)
        return result
    except Exception as exc:
        await write_audit_log(session_id=session_id, tool_name="move_task_stage",
                              args=args, result=None, error=str(exc))
        raise


@_register({
    "type": "function",
    "function": {
        "name": "move_task_stage",
        "description": "Move a Bitrix24 task to a different kanban stage.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Bitrix task ID"},
                "stage_id": {"type": "integer", "description": "Target kanban stage ID"},
            },
            "required": ["task_id", "stage_id"],
        },
    },
    "write": True,
})
async def _move_task_stage_registered(
    task_id: int, stage_id: int, **_: Any
) -> dict[str, Any]:
    async with BitrixClient() as client:
        return await _move_task_stage_tool(client=client, task_id=task_id, stage_id=stage_id)
