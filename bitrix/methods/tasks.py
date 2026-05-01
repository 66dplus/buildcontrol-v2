"""
Tasks methods wrapper for Bitrix24 REST API.
"""

from typing import Any, Dict, Optional

from bitrix.client import BitrixClient


async def ensure_uf_etap_field(client: BitrixClient) -> str:
    """
    Ensure the UF_ETAP custom field exists on tasks. Creates it if absent.

    Returns:
        The field code: "UF_ETAP"
    """
    field_code = "UF_ETAP"
    try:
        await client.call("task.item.userfield.add", {
            "PARAMS": {
                "USER_TYPE_ID": "string",
                "FIELD_NAME": field_code,
                "XML_ID": field_code,
                "LABEL": "Этап",
                "SORT": 100,
                "MULTIPLE": "N",
                "MANDATORY": "N",
            }
        })
    except ValueError as e:
        err = str(e).lower()
        if not any(kw in err for kw in ["already exists", "уже существует", "already"]):
            raise
    return field_code


async def create_task(
    client: BitrixClient,
    title: str,
    responsible_id: int = 1,
    created_by: int = 1,
    description: Optional[str] = None,
    deadline: Optional[str] = None,
    start_date_plan: Optional[str] = None,
    end_date_plan: Optional[str] = None,
    group_id: Optional[int] = None,
    uf_fields: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Create a new task.

    Args:
        client: BitrixClient instance
        title: Task title
        responsible_id: User ID of task executor (default: 1)
        created_by: User ID of task creator (default: 1)
        description: Optional task description
        deadline: Optional planned end date (ISO-8601 format: YYYY-MM-DD)
        start_date_plan: Optional planned start date (ISO-8601 format: YYYY-MM-DD)
        end_date_plan: Optional planned end date (ISO-8601 format: YYYY-MM-DD)
        group_id: Project/workgroup ID to link the task to
        uf_fields: Optional dict of custom UF_ fields to set (e.g. {"UF_ETAP": "4. Стены"})

    Returns:
        Created task ID

    Raises:
        ValueError: If API call fails
    """
    fields: Dict[str, Any] = {
        "TITLE": title,
        "RESPONSIBLE_ID": responsible_id,
        "CREATED_BY": created_by,
    }

    if description:
        fields["DESCRIPTION"] = description
    if start_date_plan and not end_date_plan:
        end_date_plan = deadline or start_date_plan
    if end_date_plan and not start_date_plan:
        start_date_plan = end_date_plan
    if end_date_plan and not deadline:
        deadline = end_date_plan

    if deadline:
        fields["DEADLINE"] = deadline
    if start_date_plan:
        fields["START_DATE_PLAN"] = start_date_plan
    if end_date_plan:
        fields["END_DATE_PLAN"] = end_date_plan
    if group_id:
        fields["GROUP_ID"] = group_id
    if uf_fields:
        fields.update(uf_fields)

    result = await client.call("tasks.task.add", {"fields": fields})
    return result["result"]["task"]["id"]


async def get_task_stages(client: BitrixClient, group_id: int) -> list[dict]:
    """
    Return kanban stages for a workgroup, sorted by SORT ascending.

    Each entry: {id, title, sort, system_type}
    system_type values: NEW, PROGRESS, WORK, REVIEW, FINISH (or None)
    """
    resp = await client.call("task.stages.get", {"entityId": group_id})
    raw = resp.get("result", {})
    stages = list(raw.values()) if isinstance(raw, dict) else raw
    return sorted(stages, key=lambda s: int(s.get("SORT", 0)))


_STAGE_SYSTEM_TYPE_RU: Dict[str, str] = {
    "NEW": "Новая",
    "PROGRESS": "В процессе",
    "WORK": "В работе",
    "REVIEW": "На проверке",
    "FINISH": "Завершена",
}


def stage_display_name(stages: list[dict], stage_id: Any) -> Optional[str]:
    """
    Map a kanban stage_id to its Russian display name.

    Mirrors api_stages() / _resolve_stage_system_type() position fallback:
    Bitrix returns SYSTEM_TYPE = null for custom stages, so for stages without
    a SYSTEM_TYPE we use position — first = «Новая», last = «Завершена»,
    middle = stage's TITLE (or «В работе» if blank).
    """
    if stage_id in (None, "", 0):
        return None
    sid = str(stage_id)
    for index, stage in enumerate(stages):
        if str(stage.get("ID", "")) != sid:
            continue
        sys_type = stage.get("SYSTEM_TYPE") or None
        if sys_type and sys_type in _STAGE_SYSTEM_TYPE_RU:
            return _STAGE_SYSTEM_TYPE_RU[sys_type]
        if index == 0:
            return "Новая"
        if index == len(stages) - 1:
            return "Завершена"
        return (stage.get("TITLE") or "").strip() or "В работе"
    return None


async def list_task_stage_ids(client: BitrixClient, group_id: int) -> Dict[str, str]:
    """
    Return {bitrix_task_id: kanban_stage_id} for every task in the workgroup.

    Uses tasks.task.list with a STAGE_ID select; pages through results 50 at a time.
    """
    out: Dict[str, str] = {}
    start = 0
    while True:
        resp = await client.call("tasks.task.list", {
            "filter": {"GROUP_ID": group_id},
            "select": ["ID", "STAGE_ID"],
            "start": start,
        })
        result = resp.get("result", {}) or {}
        tasks_list = result.get("tasks", []) or []
        for t in tasks_list:
            tid = str(t.get("id") or t.get("ID") or "").strip()
            sid = str(t.get("stageId") or t.get("STAGE_ID") or "").strip()
            if tid:
                out[tid] = sid
        next_start = resp.get("next")
        if next_start is None or not tasks_list:
            break
        start = int(next_start)
    return out


async def move_task_to_stage(client: BitrixClient, task_id: int, stage_id: int) -> bool:
    """Move a CRM task to the specified kanban stage."""
    resp = await client.call("task.stages.movetask", {"id": task_id, "stageId": stage_id})
    return bool(resp.get("result", False))


async def add_task_comment(client: BitrixClient, task_id: int, message: str) -> int:
    """Add a comment to a task. Returns the new comment ID."""
    resp = await client.call("task.commentitem.add", {
        "TASKID": task_id,
        "FIELDS": {"POST_MESSAGE": message},
    })
    return int(resp.get("result", 0))


async def find_task_by_title(client: BitrixClient, group_id: int, title: str) -> Optional[int]:
    """
    Fallback lookup: find a CRM task by GROUP_ID + TITLE match.
    Used for projects imported before the Bitrix Task ID link was stored.

    Returns task ID or None if not found.
    """
    resp = await client.call("tasks.task.list", {
        "filter": {"GROUP_ID": group_id, "TITLE": title},
        "select": ["ID", "TITLE"],
    })
    tasks_list = resp.get("result", {}).get("tasks", [])
    if tasks_list:
        return int(tasks_list[0]["id"])
    return None


async def start_task(client: BitrixClient, task_id: int) -> None:
    """Call tasks.task.start — moves task to In Progress status."""
    try:
        await client.call("tasks.task.start", {"taskId": task_id})
    except Exception as e:
        err = str(e).lower()
        # Suppress "already in progress" and "action not available" (permission/state
        # mismatch) — the kanban stage move already repositioned the task visually.
        if not any(kw in err for kw in ["already", "не доступно", "not available", "доступн"]):
            raise


async def complete_task(client: BitrixClient, task_id: int) -> None:
    """Call tasks.task.complete — marks task as done."""
    try:
        await client.call("tasks.task.complete", {"taskId": task_id})
    except Exception as e:
        err = str(e).lower()
        if not any(kw in err for kw in ["already", "не доступно", "not available", "доступн"]):
            raise


async def create_subtask(
    client: BitrixClient,
    parent_id: int,
    title: str,
    deadline: Optional[str] = None,
    start_date_plan: Optional[str] = None,
    end_date_plan: Optional[str] = None,
    group_id: Optional[int] = None,
    responsible_id: int = 1,
) -> int:
    """
    Create a child task (subtask) linked to a parent task via PARENT_ID.

    Planned dates are sent as START_DATE_PLAN + END_DATE_PLAN pair.

    Returns:
        Created subtask ID
    """
    fields: Dict[str, Any] = {
        "TITLE": title,
        "PARENT_ID": parent_id,
        "RESPONSIBLE_ID": responsible_id,
        "CREATED_BY": 1,
    }
    if start_date_plan and not end_date_plan:
        end_date_plan = deadline or start_date_plan
    if end_date_plan and not start_date_plan:
        start_date_plan = end_date_plan
    if end_date_plan and not deadline:
        deadline = end_date_plan
    if deadline:
        fields["DEADLINE"] = deadline
    if start_date_plan:
        fields["START_DATE_PLAN"] = start_date_plan
    if end_date_plan:
        fields["END_DATE_PLAN"] = end_date_plan
    if group_id:
        fields["GROUP_ID"] = group_id

    result = await client.call("tasks.task.add", {"fields": fields})
    return result["result"]["task"]["id"]


async def get_subtasks(client: BitrixClient, parent_task_id: int) -> list[dict]:
    """Return all child tasks of a parent task."""
    resp = await client.call("tasks.task.list", {
        "filter": {"PARENT_ID": parent_task_id},
        "select": ["ID", "TITLE", "DEADLINE", "START_DATE_PLAN", "STATUS"],
    })
    return resp.get("result", {}).get("tasks", [])


async def create_tasks_batch(
    client: BitrixClient,
    tasks_data: list[Dict[str, Any]],
) -> list[int]:
    """
    Create multiple tasks.

    Args:
        client: BitrixClient instance
        tasks_data: List of task data dicts (title, description, deadline, etc.)

    Returns:
        List of created task IDs
    """
    task_ids = []
    for task_data in tasks_data:
        task_id = await create_task(client, **task_data)
        task_ids.append(task_id)
    return task_ids


async def list_root_task_ids(client: BitrixClient, group_id: int) -> set[int]:
    """
    Return all root task IDs in a project using ONLY_ROOT_TASKS filter.

    This excludes subtasks from the selection and is used by the foreman widget
    to show only parent tasks.
    """
    root_ids: set[int] = set()
    start = 0

    while True:
        resp = await client.call("tasks.task.list", {
            "filter": {"GROUP_ID": group_id, "ONLY_ROOT_TASKS": "Y"},
            "select": ["ID"],
            "start": start,
        })
        result_obj = resp.get("result", {})
        if isinstance(result_obj, dict):
            tasks_list = result_obj.get("tasks", [])
        elif isinstance(result_obj, list):
            tasks_list = result_obj
        else:
            tasks_list = []
        for task in tasks_list:
            if not isinstance(task, dict):
                continue
            try:
                root_ids.add(int(task.get("id") or task.get("ID")))
            except (KeyError, TypeError, ValueError):
                continue

        next_start = resp.get("next")
        if next_start is None:
            break
        try:
            start = int(next_start)
        except (TypeError, ValueError):
            break

    return root_ids
