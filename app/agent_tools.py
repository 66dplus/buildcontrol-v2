"""
Write-action tool registry for the web AI chat.

These tools are intentionally NOT part of the Telegram agent — they propose
actions that require explicit user confirmation in the SPA UI before anything
is executed in Bitrix24.

Flow:
  1. Agent calls a write tool → handler returns a pending action dict (nothing is
     executed in Bitrix24 yet).
  2. agent_chat.stream_director_query detects the pending action, stores it in
     PENDING_ACTIONS keyed by a UUID, and yields an SSE ``event: action`` event.
  3. Frontend shows ConfirmActionCard; user clicks Confirm.
  4. POST /api/agent/confirm → execute_pending_action(action_id) runs the real
     Bitrix24 call and writes an audit log row.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from bitrix.client import BitrixClient
from bitrix.methods import tasks as bx_tasks
from config import settings
from db.database import get_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pending action store (in-memory; survives only while the server is up)
# ---------------------------------------------------------------------------

# {action_id: {"action_type": str, "params": dict}}
PENDING_ACTIONS: Dict[str, Dict[str, Any]] = {}


def _queue(action_type: str, params: dict, display: dict) -> dict:
    """Return a pending-action sentinel — does NOT touch Bitrix24."""
    return {
        "__pending_action__": True,
        "action_type": action_type,
        "params": params,
        "display": display,  # {title: str, fields: [{label, value}]}
    }


# ---------------------------------------------------------------------------
# Write tool registry
# ---------------------------------------------------------------------------

ToolHandler = Callable[..., Coroutine[Any, Any, Any]]
ToolEntry = Tuple[Dict[str, Any], ToolHandler]

WRITE_TOOL_REGISTRY: Dict[str, ToolEntry] = {}


def _register(schema: Dict[str, Any]) -> Callable[[ToolHandler], ToolHandler]:
    def decorator(fn: ToolHandler) -> ToolHandler:
        WRITE_TOOL_REGISTRY[schema["function"]["name"]] = (schema, fn)
        return fn
    return decorator


@_register({
    "type": "function",
    "function": {
        "name": "create_task",
        "description": (
            "Создать новую задачу в проекте Bitrix24 и SQLite. "
            "Требует подтверждения директора перед выполнением. "
            "Используй list_projects() для получения project_id, "
            "query_database() для поиска responsible_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "ID проекта в SQLite (из list_projects)",
                },
                "title": {
                    "type": "string",
                    "description": "Название задачи",
                },
                "responsible_id": {
                    "type": "integer",
                    "description": "Bitrix24 user ID ответственного",
                },
                "description": {
                    "type": "string",
                    "description": "Описание задачи (необязательно)",
                },
                "deadline": {
                    "type": "string",
                    "description": "Срок выполнения в формате YYYY-MM-DD (необязательно)",
                },
            },
            "required": ["project_id", "title", "responsible_id"],
        },
    },
})
async def _tool_create_task(
    project_id: int,
    title: str,
    responsible_id: int,
    description: Optional[str] = None,
    deadline: Optional[str] = None,
    **_: Any,
) -> dict:
    fields = [
        {"label": "Название", "value": title},
        {"label": "Ответственный (ID)", "value": str(responsible_id)},
    ]
    if deadline:
        fields.append({"label": "Срок", "value": deadline})
    if description:
        fields.append({"label": "Описание", "value": description[:80]})
    return _queue(
        "create_task",
        {"project_id": project_id, "title": title, "responsible_id": responsible_id,
         "description": description, "deadline": deadline},
        {"title": f'Создать задачу: «{title}»', "fields": fields},
    )


@_register({
    "type": "function",
    "function": {
        "name": "add_comment",
        "description": (
            "Добавить комментарий к задаче Bitrix24. "
            "Требует подтверждения. "
            "Используй query_database() чтобы найти bitrix_task_id по названию задачи."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bitrix_task_id": {
                    "type": "integer",
                    "description": "ID задачи Bitrix24 (поле bitrix_task_id в таблице tasks)",
                },
                "message": {
                    "type": "string",
                    "description": "Текст комментария",
                },
            },
            "required": ["bitrix_task_id", "message"],
        },
    },
})
async def _tool_add_comment(
    bitrix_task_id: int,
    message: str,
    **_: Any,
) -> dict:
    return _queue(
        "add_comment",
        {"bitrix_task_id": bitrix_task_id, "message": message},
        {
            "title": "Добавить комментарий к задаче",
            "fields": [
                {"label": "Задача (Bitrix ID)", "value": str(bitrix_task_id)},
                {"label": "Комментарий", "value": message[:120]},
            ],
        },
    )


@_register({
    "type": "function",
    "function": {
        "name": "assign_user",
        "description": (
            "Назначить ответственного за задачу Bitrix24 (обновить RESPONSIBLE_ID). "
            "Требует подтверждения."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bitrix_task_id": {
                    "type": "integer",
                    "description": "ID задачи Bitrix24",
                },
                "responsible_id": {
                    "type": "integer",
                    "description": "Bitrix24 user ID нового ответственного",
                },
            },
            "required": ["bitrix_task_id", "responsible_id"],
        },
    },
})
async def _tool_assign_user(
    bitrix_task_id: int,
    responsible_id: int,
    **_: Any,
) -> dict:
    return _queue(
        "assign_user",
        {"bitrix_task_id": bitrix_task_id, "responsible_id": responsible_id},
        {
            "title": "Переназначить ответственного",
            "fields": [
                {"label": "Задача (Bitrix ID)", "value": str(bitrix_task_id)},
                {"label": "Новый ответственный (ID)", "value": str(responsible_id)},
            ],
        },
    )


@_register({
    "type": "function",
    "function": {
        "name": "move_task_stage",
        "description": (
            "Переместить задачу Bitrix24 на другой канбан-этап. "
            "Требует подтверждения. "
            "Используй query_database() чтобы найти bitrix_task_id и stage_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bitrix_task_id": {
                    "type": "integer",
                    "description": "ID задачи Bitrix24",
                },
                "stage_id": {
                    "type": "integer",
                    "description": "ID нового этапа канбана Bitrix24",
                },
                "stage_name": {
                    "type": "string",
                    "description": "Название этапа (для отображения в карточке подтверждения)",
                },
            },
            "required": ["bitrix_task_id", "stage_id"],
        },
    },
})
async def _tool_move_task_stage(
    bitrix_task_id: int,
    stage_id: int,
    stage_name: str = "",
    **_: Any,
) -> dict:
    return _queue(
        "move_task_stage",
        {"bitrix_task_id": bitrix_task_id, "stage_id": stage_id},
        {
            "title": "Переместить задачу на этап",
            "fields": [
                {"label": "Задача (Bitrix ID)", "value": str(bitrix_task_id)},
                {"label": "Этап", "value": stage_name or str(stage_id)},
            ],
        },
    )


# ---------------------------------------------------------------------------
# Dispatch helper (mirrors _dispatch in telegram_agent.py)
# ---------------------------------------------------------------------------

async def dispatch_write(name: str, arguments_json: str) -> Any:
    entry = WRITE_TOOL_REGISTRY.get(name)
    if not entry:
        return {"error": f"Unknown write tool: {name}"}
    _, handler = entry
    try:
        kwargs = json.loads(arguments_json) if arguments_json else {}
        return await handler(**kwargs)
    except Exception as exc:
        logger.exception("Write tool '%s' raised: %s", name, exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Execution (called after user confirms)
# ---------------------------------------------------------------------------

async def execute_pending_action(action_id: str) -> dict:
    """
    Look up a queued action, execute it against Bitrix24, record audit log.
    Removes the action from PENDING_ACTIONS on first call (idempotent guard).
    """
    action = PENDING_ACTIONS.pop(action_id, None)
    if action is None:
        return {"error": "action_not_found"}

    action_type = action["action_type"]
    params = action["params"]
    result: dict = {}

    try:
        client = BitrixClient(settings.bitrix24_webhook_url)

        if action_type == "create_task":
            bx_task_id = await bx_tasks.create_task(
                client,
                title=params["title"],
                responsible_id=params["responsible_id"],
                description=params.get("description"),
                deadline=params.get("deadline"),
            )
            # Mirror to SQLite
            async with get_db() as conn:
                await conn.execute(
                    """
                    INSERT INTO tasks (project_id, bitrix_task_id, phase, task_name)
                    VALUES (?, ?, 'AI Created', ?)
                    ON CONFLICT(project_id, phase, task_name) DO UPDATE
                      SET bitrix_task_id = excluded.bitrix_task_id
                    """,
                    (params["project_id"], str(bx_task_id), params["title"]),
                )
                await conn.commit()
            result = {"bitrix_task_id": bx_task_id}

        elif action_type == "add_comment":
            comment_id = await bx_tasks.add_task_comment(
                client,
                task_id=params["bitrix_task_id"],
                message=params["message"],
            )
            result = {"comment_id": comment_id}

        elif action_type == "assign_user":
            await client.call("tasks.task.update", {
                "taskId": params["bitrix_task_id"],
                "fields": {"RESPONSIBLE_ID": params["responsible_id"]},
            })
            result = {"ok": True}

        elif action_type == "move_task_stage":
            moved = await bx_tasks.move_task_to_stage(
                client,
                task_id=params["bitrix_task_id"],
                stage_id=params["stage_id"],
            )
            result = {"ok": moved}

        else:
            result = {"error": f"Unknown action_type: {action_type}"}

    except Exception as exc:
        logger.exception("execute_pending_action failed: %s", exc)
        await _write_audit_log(action_type, params, {"error": str(exc)}, "failed")
        return {"error": str(exc)}

    await _write_audit_log(action_type, params, result, "confirmed")
    return result


async def _write_audit_log(
    action_type: str,
    params: dict,
    result: dict,
    status: str,
) -> None:
    try:
        async with get_db() as conn:
            await conn.execute(
                """
                INSERT INTO agent_audit_log (action_type, params, result, status)
                VALUES (?, ?, ?, ?)
                """,
                (
                    action_type,
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    status,
                ),
            )
            await conn.commit()
    except Exception as exc:
        logger.warning("audit log write failed: %s", exc)


# ---------------------------------------------------------------------------
# System prompt appendix for write tools
# ---------------------------------------------------------------------------

WRITE_TOOLS_PROMPT = """
== ДЕЙСТВИЯ (WRITE TOOLS) ==
Ты можешь предлагать следующие действия. Каждое требует подтверждения директора.
Сначала ВСЕГДА вызывай list_projects() и query_database() для получения project_id,
bitrix_task_id, responsible_id — не угадывай эти ID.

- create_task(project_id, title, responsible_id, description?, deadline?)
  Создаёт задачу в Bitrix24 + SQLite. Предлагай только когда директор явно просит.

- add_comment(bitrix_task_id, message)
  Добавляет комментарий к задаче в Bitrix24.

- assign_user(bitrix_task_id, responsible_id)
  Назначает нового ответственного на задачу.

- move_task_stage(bitrix_task_id, stage_id, stage_name?)
  Перемещает задачу на другой этап канбана.

После вызова write-tool НЕМЕДЛЕННО ОСТАНОВИСЬ — не добавляй текст после этого.
Карточка подтверждения появится автоматически в интерфейсе.
"""
