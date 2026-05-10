"""Write tool: create_task."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.agent.audit import write_audit_log
from app.agent.tools import _register
from bitrix.client import BitrixClient
from bitrix.methods import tasks as tasks_methods
from db import repo
from db.database import get_db

logger = logging.getLogger(__name__)


async def _create_task_tool(
    *,
    client: Any,
    title: str,
    responsible_id: int = 1,
    group_id: Optional[int] = None,
    deadline: Optional[str] = None,
    description: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Core implementation — testable with DummyClient."""
    args = {"title": title, "responsible_id": responsible_id,
            "group_id": group_id, "deadline": deadline, "description": description}
    try:
        task_id = await tasks_methods.create_task(
            client, title=title, responsible_id=responsible_id,
            group_id=group_id, deadline=deadline, description=description,
        )
        if group_id:
            async with get_db() as conn:
                await repo.upsert_task(
                    conn, group_id, phase="", task_name=title,
                    bitrix_task_id=str(task_id),
                )
        result = {"task_id": task_id}
        await write_audit_log(session_id=session_id, tool_name="create_task",
                              args=args, result=result, error=None)
        return result
    except Exception as exc:
        await write_audit_log(session_id=session_id, tool_name="create_task",
                              args=args, result=None, error=str(exc))
        raise


@_register({
    "type": "function",
    "function": {
        "name": "create_task",
        "description": "Create a new task in Bitrix24 for a project.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "responsible_id": {"type": "integer", "description": "Assignee user ID"},
                "group_id": {"type": "integer", "description": "Project workgroup ID"},
                "deadline": {"type": "string", "description": "Deadline YYYY-MM-DD"},
                "description": {"type": "string", "description": "Task description"},
            },
            "required": ["title", "group_id"],
        },
    },
    "write": True,
})
async def _create_task_registered(
    title: str, group_id: int, responsible_id: int = 1,
    deadline: Optional[str] = None, description: Optional[str] = None, **_: Any,
) -> dict[str, Any]:
    async with BitrixClient() as client:
        return await _create_task_tool(
            client=client, title=title, responsible_id=responsible_id,
            group_id=group_id, deadline=deadline, description=description,
        )
