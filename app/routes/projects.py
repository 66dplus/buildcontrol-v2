import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bitrix.client import BitrixClient
from bitrix.methods import lists, tasks as tasks_methods
from db.database import get_db
from db import repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["projects"])

_LIST_META_TTL_SECONDS = 60.0
_PROJECT_LISTS_CACHE: Dict[int, tuple[float, list[dict[str, Any]]]] = {}
_LIST_META_CACHE: Dict[
    tuple[int, str],
    tuple[float, tuple[int, str, dict[str, int]]],
] = {}

_SYSTEM_TYPE_RU: Dict[str, str] = {
    "NEW": "Новая",
    "PROGRESS": "В процессе",
    "WORK": "В работе",
    "REVIEW": "На проверке",
    "FINISH": "Завершена",
}


def _cache_get(
    cache: Dict[Any, tuple[float, Any]],
    key: Any,
) -> Optional[Any]:
    """Return cached value if fresh, otherwise None."""
    cached = cache.get(key)
    if not cached:
        return None
    expires_at, value = cached
    if time.monotonic() >= expires_at:
        cache.pop(key, None)
        return None
    return value


def _cache_set(
    cache: Dict[Any, tuple[float, Any]],
    key: Any,
    value: Any,
    ttl_seconds: float = _LIST_META_TTL_SECONDS,
) -> None:
    """Store a value in a simple in-memory TTL cache."""
    cache[key] = (time.monotonic() + ttl_seconds, value)


async def _get_project_lists_cached(
    client: BitrixClient,
    project_id: int,
) -> list[dict[str, Any]]:
    """Get project's universal lists with 60s in-memory cache."""
    cached = _cache_get(_PROJECT_LISTS_CACHE, project_id)
    if cached is not None:
        return cached
    all_lists = await lists.get_lists(client, project_id)
    _cache_set(_PROJECT_LISTS_CACHE, project_id, all_lists)
    return all_lists


async def _get_list_meta_cached(
    client: BitrixClient,
    project_id: int,
    name_keyword: str,
) -> Optional[tuple[int, str, dict[str, int]]]:
    """
    Resolve list metadata (list id, iblock code, field map) with 60s cache.

    Elements are intentionally not cached to keep task/resource values fresh.
    """
    cache_key = (project_id, (name_keyword or "").strip().lower())
    cached = _cache_get(_LIST_META_CACHE, cache_key)
    if cached is not None:
        return cached

    all_lists = await _get_project_lists_cached(client, project_id)
    target = lists.find_list_by_keyword(all_lists, name_keyword)
    if not target:
        return None

    list_id = int(target["ID"])
    iblock_code = target.get("IBLOCK_CODE", "")
    fields_resp = await lists.get_fields(client, list_id, iblock_code, project_id)
    field_map = lists.resolve_field_map(fields_resp)
    meta = (list_id, iblock_code, field_map)
    _cache_set(_LIST_META_CACHE, cache_key, meta)
    return meta


async def _get_list_context(
    client: BitrixClient,
    project_id: int,
    name_keyword: str,
) -> Optional[tuple]:
    """
    Find a list by name keyword and return (list_id, iblock_code, field_map, elements).
    Returns None if no matching list found.
    """
    meta = await _get_list_meta_cached(client, project_id, name_keyword)
    if not meta:
        return None

    list_id, iblock_code, field_map = meta
    elements = await lists.get_elements(client, list_id, iblock_code, project_id)
    return list_id, iblock_code, field_map, elements


def _filter_task_elements(
    elements: list[dict[str, Any]],
    field_map: dict[str, int],
    etap: str,
    zadacha: str,
) -> list[dict[str, Any]]:
    """Filter elements by (Этап, Задача) when both values are provided."""
    if etap and zadacha:
        return lists.find_elements_by_properties(
            elements, field_map, {"Этап": etap, "Задача": zadacha},
        )
    return elements


def _build_materials_payload(
    elements: list[dict[str, Any]],
    field_map: dict[str, int],
) -> list[dict[str, Any]]:
    """Build API payload for materials list."""
    pid_unit = next(
        (pid for name, pid in field_map.items()
         if any(kw in name.lower() for kw in ["ед.", "единиц", "ед.изм", "unit"])),
        None,
    )
    pid_stock_mat = next(
        (pid for name, pid in field_map.items() if "остаток" in name.lower()), None
    )
    pid_qty_plan_mat = next(
        (pid for name, pid in field_map.items() if "объём план" in name.lower()), None
    )
    pid_qty_bought_mat = next(
        (
            pid for name, pid in field_map.items()
            if "куплено" in name.lower() and "объём" in name.lower()
        ),
        None,
    )
    pid_price_plan_mat = next(
        (
            pid for name, pid in field_map.items()
            if "цена ед" in name.lower() and "план" in name.lower()
        ),
        None,
    )

    materials: list[dict[str, Any]] = []
    for elem in elements:
        name = elem.get("NAME", "")
        if not name:
            continue

        materials.append({
            "name": name,
            "unit": lists.get_prop_value_str(elem, pid_unit) if pid_unit else "",
            "stock": float(lists.get_prop_value(elem, pid_stock_mat) or 0) if pid_stock_mat else None,
            "qty_plan": float(lists.get_prop_value(elem, pid_qty_plan_mat) or 0) if pid_qty_plan_mat else None,
            "qty_bought": float(lists.get_prop_value(elem, pid_qty_bought_mat) or 0) if pid_qty_bought_mat else None,
            "price_plan": float(lists.get_prop_value(elem, pid_price_plan_mat) or 0) if pid_price_plan_mat else None,
        })
    return materials


def _build_labor_payload(
    elements: list[dict[str, Any]],
    field_map: dict[str, int],
) -> list[dict[str, Any]]:
    """Build API payload for labor list."""
    pid_role = next(
        (
            pid for name, pid in field_map.items()
            if any(kw in name.lower() for kw in ["должность", "роль", "специальность", "role"])
        ),
        None,
    )
    workers: list[dict[str, Any]] = []
    for elem in elements:
        name = elem.get("NAME", "")
        if not name:
            continue
        workers.append({
            "name": name,
            "role": lists.get_prop_value_str(elem, pid_role) if pid_role else "",
        })
    return workers


def _build_equipment_payload(
    elements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build API payload for equipment list."""
    equipment: list[dict[str, Any]] = []
    for elem in elements:
        name = elem.get("NAME", "")
        if not name:
            continue
        equipment.append({"name": name})
    return equipment


def _build_subtasks_payload(
    elements: list[dict[str, Any]],
    field_map: dict[str, int],
) -> list[dict[str, Any]]:
    """Build API payload for subtasks list."""
    pid_deadline = lists._resolve_filter_pid(field_map, "ок. план")
    if not pid_deadline:
        pid_deadline = lists._resolve_filter_pid(field_map, "ок план")
    pid_start_plan = lists._resolve_filter_pid(field_map, "нач. план")
    if not pid_start_plan:
        pid_start_plan = lists._resolve_filter_pid(field_map, "нач план")
    pid_status = lists._resolve_filter_pid(field_map, "статус")
    pid_date_start_fact = lists._resolve_filter_pid(field_map, "нач. факт")
    if not pid_date_start_fact:
        pid_date_start_fact = lists._resolve_filter_pid(field_map, "нач факт")
    pid_date_done_fact = lists._resolve_filter_pid(field_map, "ок. факт")
    if not pid_date_done_fact:
        pid_date_done_fact = lists._resolve_filter_pid(field_map, "ок факт")
    pid_bsubtask_id = lists._resolve_filter_pid(field_map, "bitrix subtask id")
    pid_order = lists._resolve_filter_pid(field_map, "№")

    subtasks: list[dict[str, Any]] = []
    for elem in elements:
        title = elem.get("NAME", "")
        if not title:
            continue
        subtasks.append({
            "element_id": int(elem.get("ID", 0)),
            "title": title,
            "order": int(lists.get_prop_value(elem, pid_order) or 0) if pid_order else 0,
            "deadline_plan": lists.get_prop_value_str(elem, pid_deadline) if pid_deadline else None,
            "date_start_plan": lists.get_prop_value_str(elem, pid_start_plan) if pid_start_plan else None,
            "status": lists.get_prop_value_str(elem, pid_status) if pid_status else "Новая",
            "date_fact_start": lists.get_prop_value_str(elem, pid_date_start_fact) if pid_date_start_fact else None,
            "date_fact_done": lists.get_prop_value_str(elem, pid_date_done_fact) if pid_date_done_fact else None,
            "bitrix_subtask_id": int(lists.get_prop_value(elem, pid_bsubtask_id) or 0) if pid_bsubtask_id else None,
        })

    subtasks.sort(key=lambda item: (item["order"], item["element_id"]))
    return subtasks


async def _load_task_context_payload(
    client: BitrixClient,
    project_id: int,
    etap: str,
    zadacha: str,
) -> dict[str, list[dict[str, Any]]]:
    """Load all task-linked resources/subtasks in one payload for widget speed."""
    payload: dict[str, list[dict[str, Any]]] = {
        "materials": [],
        "labor": [],
        "equipment": [],
        "subtasks": [],
    }

    materials_ctx = await _get_list_context(client, project_id, "материал")
    if materials_ctx:
        _, _, field_map, elements = materials_ctx
        filtered = _filter_task_elements(elements, field_map, etap, zadacha)
        payload["materials"] = _build_materials_payload(filtered, field_map)

    labor_ctx = await _get_list_context(client, project_id, "трудозатрат")
    if labor_ctx:
        _, _, field_map, elements = labor_ctx
        filtered = _filter_task_elements(elements, field_map, etap, zadacha)
        payload["labor"] = _build_labor_payload(filtered, field_map)

    equipment_ctx = await _get_list_context(client, project_id, "техник")
    if equipment_ctx:
        _, _, field_map, elements = equipment_ctx
        filtered = _filter_task_elements(elements, field_map, etap, zadacha)
        payload["equipment"] = _build_equipment_payload(filtered)

    subtasks_ctx = await _get_list_context(client, project_id, "подзадач")
    if subtasks_ctx:
        _, _, field_map, elements = subtasks_ctx
        filtered = _filter_task_elements(elements, field_map, etap, zadacha)
        payload["subtasks"] = _build_subtasks_payload(filtered, field_map)

    return payload


@router.get("/api/projects")
async def api_projects() -> JSONResponse:
    """List all active projects for the report form dropdown."""
    async with get_db() as conn:
        projects = await repo.get_projects(conn)
    return JSONResponse(content=projects)


@router.get("/api/projects/{project_id}/materials")
async def api_materials(project_id: int, request: Request) -> JSONResponse:
    """
    Return material names/units from SQLite.
    Optional query params ?etap=X&zadacha=Y to filter by task.
    """
    etap = request.query_params.get("etap", "").strip() or None
    zadacha = request.query_params.get("zadacha", "").strip() or None
    async with get_db() as conn:
        if etap or zadacha:
            rows = await repo.get_materials(conn, project_id, etap, zadacha)
            materials = [
                {
                    "name": r["material_name"],
                    "unit": r["unit"],
                    "stock": r["qty_stock"],
                    "qty_plan": r["qty_plan"],
                    "qty_bought": r["qty_bought"],
                    "price_plan": r["price_plan"],
                }
                for r in rows
            ]
        else:
            rows = await repo.get_materials_for_buyer(conn, project_id)
            materials = [
                {
                    "name": r["material_name"],
                    "unit": r["unit"],
                    "qty_plan": r["qty_plan"],
                    "qty_bought": r["qty_bought"],
                    "price_plan": r["price_plan"],
                }
                for r in rows
            ]
    return JSONResponse(content=materials)


@router.get("/api/projects/{project_id}/labor")
async def api_labor(project_id: int, request: Request) -> JSONResponse:
    """
    Return worker specialties from SQLite.
    Optional query params ?etap=X&zadacha=Y to filter by task.
    """
    etap = request.query_params.get("etap", "").strip() or None
    zadacha = request.query_params.get("zadacha", "").strip() or None
    async with get_db() as conn:
        rows = await repo.get_labor(conn, project_id, etap, zadacha)
    workers = [{"name": r["specialty"], "role": ""} for r in rows]
    return JSONResponse(content=workers)


@router.get("/api/projects/{project_id}/task-context")
async def api_task_context(project_id: int, request: Request) -> JSONResponse:
    """
    Return materials, labor, equipment from SQLite + subtasks from Bitrix.
    Query params: ?etap=X&zadacha=Y
    """
    etap = request.query_params.get("etap", "").strip() or None
    zadacha = request.query_params.get("zadacha", "").strip() or None

    async with get_db() as conn:
        mat_rows = await repo.get_materials(conn, project_id, etap, zadacha)
        lab_rows = await repo.get_labor(conn, project_id, etap, zadacha)
        eq_rows = await repo.get_equipment(conn, project_id, etap, zadacha)

    materials = [
        {"name": r["material_name"], "unit": r["unit"], "stock": r["qty_stock"],
         "qty_plan": r["qty_plan"], "qty_bought": r["qty_bought"], "price_plan": r["price_plan"]}
        for r in mat_rows
    ]
    labor = [{"name": r["specialty"], "role": ""} for r in lab_rows]
    equipment = [{"name": r["equipment_name"]} for r in eq_rows]

    subtasks: list[dict[str, Any]] = []
    try:
        async with BitrixClient() as client:
            subtasks_ctx = await _get_list_context(client, project_id, "подзадач")
            if subtasks_ctx:
                _, _, field_map, elements = subtasks_ctx
                filtered = _filter_task_elements(elements, field_map, etap or "", zadacha or "")
                subtasks = _build_subtasks_payload(filtered, field_map)
    except Exception as exc:
        logger.warning("api_task_context: subtasks Bitrix call failed: %s", exc)

    return JSONResponse(content={"materials": materials, "labor": labor, "equipment": equipment, "subtasks": subtasks})


@router.get("/api/projects/{project_id}/tasks")
async def api_tasks(project_id: int) -> JSONResponse:
    """
    Return tasks from SQLite. Each task has etap, zadacha, budget_plan, element_id, bitrix_task_id.
    """
    async with get_db() as conn:
        rows = await repo.get_tasks(conn, project_id)
    task_list = [
        {
            "etap": r["phase"],
            "zadacha": r["task_name"],
            "budget_plan": r["budget_plan"],
            "element_id": r["id"],
            "bitrix_task_id": r["bitrix_task_id"],
        }
        for r in rows
    ]
    return JSONResponse(content=task_list)


@router.get("/api/projects/{project_id}/stages")
async def api_stages(project_id: int) -> JSONResponse:
    """
    Return kanban stages for the project workgroup.
    Used by the foreman widget to populate the stage dropdown.
    Titles are mapped to Russian for known SYSTEM_TYPE values.
    """
    async with BitrixClient() as client:
        stages = await tasks_methods.get_task_stages(client, project_id)
    result = []
    for i, s in enumerate(stages):
        sys_type = s.get("SYSTEM_TYPE") or None
        if sys_type in _SYSTEM_TYPE_RU:
            title = _SYSTEM_TYPE_RU[sys_type]
        elif i == 0:
            title = "Новая"
            sys_type = "NEW"
        elif i == len(stages) - 1:
            title = "Завершена"
            sys_type = "FINISH"
        else:
            title = s.get("TITLE", "")
        result.append({
            "id": int(s["ID"]),
            "title": title,
            "sort": int(s.get("SORT", 0)),
            "system_type": sys_type,
        })
    return JSONResponse(content=result)


@router.get("/api/projects/{project_id}/subtasks")
async def api_subtasks(project_id: int, request: Request) -> JSONResponse:
    """
    Return subtasks for a specific (etap, zadacha) from the "6. Подзадачи" list.
    Query params: ?etap=X&zadacha=Y
    Used by the foreman form to show per-task subtask completion UI.
    Returns empty list for v3 projects (no подзадачи list).
    """
    etap = request.query_params.get("etap", "").strip()
    zadacha = request.query_params.get("zadacha", "").strip()

    async with BitrixClient() as client:
        ctx = await _get_list_context(client, project_id, "подзадач")
        if not ctx:
            return JSONResponse(content=[])

        _, _, field_map, elements = ctx
        filtered = _filter_task_elements(elements, field_map, etap, zadacha)
        result = _build_subtasks_payload(filtered, field_map)

    return JSONResponse(content=result)


@router.get("/api/projects/{project_id}/equipment")
async def api_equipment(project_id: int, request: Request) -> JSONResponse:
    """
    Return equipment items from the project's "5. Техника" list.
    Optional query params ?etap=X&zadacha=Y to filter by task.
    """
    etap = request.query_params.get("etap", "").strip()
    zadacha = request.query_params.get("zadacha", "").strip()

    async with BitrixClient() as client:
        ctx = await _get_list_context(client, project_id, "техник")
        if not ctx:
            return JSONResponse(content=[])

        _, _, field_map, elements = ctx
        filtered = _filter_task_elements(elements, field_map, etap, zadacha)
        equipment = _build_equipment_payload(filtered)

    return JSONResponse(content=equipment)


@router.get("/api/projects/{project_id}/tasks-full")
async def api_tasks_full(project_id: int) -> JSONResponse:
    """
    Full task rows from SQLite for the SPA Project Detail (Stages tab).

    Differs from /api/projects/{id}/tasks (foreman dropdown) by returning
    every column — dates, completion, stage, budget plan/actual.
    """
    async with get_db() as conn:
        rows = await repo.get_tasks(conn, project_id)
    return JSONResponse(content=rows)


@router.get("/api/projects/{project_id}/materials-all")
async def api_materials_all(
    project_id: int,
    phase: Optional[str] = None,
    task: Optional[str] = None,
) -> JSONResponse:
    """All materials for a project, optionally filtered by ?phase=&task=."""
    async with get_db() as conn:
        rows = await repo.get_materials(conn, project_id, phase=phase, task_name=task)
    return JSONResponse(content=rows)


@router.get("/api/projects/{project_id}/labor-all")
async def api_labor_all(
    project_id: int,
    phase: Optional[str] = None,
    task: Optional[str] = None,
) -> JSONResponse:
    """All labor rows for a project, optionally filtered by ?phase=&task=."""
    async with get_db() as conn:
        rows = await repo.get_labor(conn, project_id, phase=phase, task_name=task)
    return JSONResponse(content=rows)


@router.get("/api/projects/{project_id}/equipment-all")
async def api_equipment_all(
    project_id: int,
    phase: Optional[str] = None,
    task: Optional[str] = None,
) -> JSONResponse:
    """All equipment rows for a project, optionally filtered by ?phase=&task=."""
    async with get_db() as conn:
        rows = await repo.get_equipment(conn, project_id, phase=phase, task_name=task)
    return JSONResponse(content=rows)
