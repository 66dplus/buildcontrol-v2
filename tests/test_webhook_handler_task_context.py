"""Tests for task context endpoint and v4 parent kanban movement."""

import json
from typing import Any, Optional

import pytest
from starlette.requests import Request

from app import webhook_handler


def _make_element(element_id: int, name: str, props: dict[int, Any]) -> dict[str, Any]:
    """Create a Bitrix-like list element with PROPERTY_N fields."""
    element: dict[str, Any] = {
        "ID": str(element_id),
        "NAME": name,
    }
    for prop_id, value in props.items():
        element[f"PROPERTY_{prop_id}"] = {"0": "" if value is None else str(value)}
    return element


def _make_request(query: str) -> Request:
    """Create a minimal Starlette request object for endpoint unit tests."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/projects/1/task-context",
        "query_string": query.encode("utf-8"),
        "headers": [],
    }
    return Request(scope)


def test_stage_resolution_fallback_with_null_system_type() -> None:
    """Middle stage must fallback to PROGRESS; first/last to NEW/FINISH."""
    stages = [
        {"ID": "101", "SORT": "100", "SYSTEM_TYPE": None, "TITLE": "Новая"},
        {"ID": "102", "SORT": "200", "SYSTEM_TYPE": None, "TITLE": "В работе"},
        {"ID": "103", "SORT": "300", "SYSTEM_TYPE": None, "TITLE": "Завершена"},
    ]

    assert webhook_handler._resolve_stage_system_type(stages, 101) == "NEW"
    assert webhook_handler._resolve_stage_system_type(stages, 102) == "PROGRESS"
    assert webhook_handler._resolve_stage_system_type(stages, 103) == "FINISH"
    assert webhook_handler._resolve_parent_stage_targets(stages) == (102, 103)


@pytest.mark.asyncio
async def test_api_task_context_returns_filtered_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """task-context endpoint should return all sections filtered by etap/zadacha."""
    from contextlib import asynccontextmanager

    # Mock get_db to avoid opening a real SQLite file
    @asynccontextmanager
    async def fake_get_db():
        yield object()

    monkeypatch.setattr(webhook_handler, "get_db", fake_get_db)

    async def fake_get_materials(conn: object, project_id: int, phase: Any = None, task_name: Any = None) -> list:
        all_rows = [
            {"material_name": "Бетон", "unit": "м3", "qty_stock": 10, "qty_plan": 20, "qty_bought": 5, "price_plan": 0},
            {"material_name": "Песок", "unit": "кг", "qty_stock": 7, "qty_plan": 10, "qty_bought": 3, "price_plan": 0},
        ]
        if phase == "Этап 1" and task_name == "Задача 1":
            return [all_rows[0]]
        return all_rows

    async def fake_get_labor(conn: object, project_id: int, phase: Any = None, task_name: Any = None) -> list:
        all_rows = [
            {"specialty": "Иванов", "phase": "Этап 1", "task_name": "Задача 1"},
            {"specialty": "Петров", "phase": "Этап 2", "task_name": "Задача 2"},
        ]
        if phase == "Этап 1" and task_name == "Задача 1":
            return [all_rows[0]]
        return all_rows

    async def fake_get_equipment(conn: object, project_id: int, phase: Any = None, task_name: Any = None) -> list:
        all_rows = [
            {"equipment_name": "Кран", "phase": "Этап 1", "task_name": "Задача 1"},
            {"equipment_name": "Экскаватор", "phase": "Этап 2", "task_name": "Задача 2"},
        ]
        if phase == "Этап 1" and task_name == "Задача 1":
            return [all_rows[0]]
        return all_rows

    monkeypatch.setattr(webhook_handler.repo, "get_materials", fake_get_materials)
    monkeypatch.setattr(webhook_handler.repo, "get_labor", fake_get_labor)
    monkeypatch.setattr(webhook_handler.repo, "get_equipment", fake_get_equipment)

    # Subtasks still come from Bitrix — mock _get_list_context for that only
    sub_field_map = {
        "Этап": 1,
        "Задача": 2,
        "Статус": 3,
        "Дата нач. план": 4,
        "Дата ок. план": 5,
        "№": 6,
    }
    subtasks = [
        _make_element(31, "Подзадача B", {1: "Этап 1", 2: "Задача 1", 3: "Новая", 4: "2026-04-01", 5: "2026-04-03", 6: 2}),
        _make_element(30, "Подзадача A", {1: "Этап 1", 2: "Задача 1", 3: "В работе", 4: "2026-04-01", 5: "2026-04-02", 6: 1}),
    ]

    class DummyClientCtx:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

    monkeypatch.setattr(webhook_handler, "BitrixClient", lambda: DummyClientCtx())

    async def fake_get_list_context(client: object, project_id: int, keyword: str) -> Any:
        if keyword == "подзадач":
            return 6, "subtasks", sub_field_map, subtasks
        return None

    monkeypatch.setattr(webhook_handler, "_get_list_context", fake_get_list_context)

    request = _make_request("etap=%D0%AD%D1%82%D0%B0%D0%BF%201&zadacha=%D0%97%D0%B0%D0%B4%D0%B0%D1%87%D0%B0%201")
    response = await webhook_handler.api_task_context(42, request)
    payload = json.loads(response.body)

    assert set(payload.keys()) == {"materials", "labor", "equipment", "subtasks"}
    assert len(payload["materials"]) == 1
    assert payload["materials"][0]["name"] == "Бетон"
    assert len(payload["labor"]) == 1
    assert payload["labor"][0]["name"] == "Иванов"
    assert len(payload["equipment"]) == 1
    assert payload["equipment"][0]["name"] == "Кран"
    assert [item["title"] for item in payload["subtasks"]] == ["Подзадача A", "Подзадача B"]


async def _run_parent_kanban_progress_case(
    monkeypatch: pytest.MonkeyPatch,
    update_status: str,
    expected_stage_id: int,
    expect_complete: bool,
) -> None:
    sub_field_map = {
        "Этап": 1,
        "Задача": 2,
        "Статус": 3,
    }
    task_field_map = {
        "Этап": 1,
        "Задача": 2,
        "Готовн. факт, %": 4,
        "Bitrix Task ID": 5,
    }

    sub_elements = [
        _make_element(101, "Подзадача 1", {1: "Этап 1", 2: "Задача 1", 3: "Новая"}),
    ]
    task_elements = [
        _make_element(201, "Задача 1", {1: "Этап 1", 2: "Задача 1", 4: 0, 5: 900}),
    ]

    async def fake_get_list_context(client: object, project_id: int, keyword: str) -> Any:
        if keyword == "подзадач":
            return 6, "subtasks", sub_field_map, sub_elements
        if keyword == "задач":
            return 2, "tasks", task_field_map, task_elements
        return None

    async def fake_get_elements(client: object, list_id: int, iblock_code: str, project_id: int) -> list[dict[str, Any]]:
        if list_id == 6:
            return sub_elements
        if list_id == 2:
            return task_elements
        return []

    async def fake_update_element(
        client: object,
        list_id: int,
        iblock_code: str,
        group_id: int,
        element_id: int,
        field_values: dict[int, Any],
        name: Optional[str] = None,
    ) -> bool:
        elements = sub_elements if list_id == 6 else task_elements
        target = next((elem for elem in elements if int(elem["ID"]) == int(element_id)), None)
        assert target is not None
        if name:
            target["NAME"] = name
        for prop_id, value in field_values.items():
            target[f"PROPERTY_{prop_id}"] = {"0": "" if value is None else str(value)}
        return True

    moved: list[tuple[int, int]] = []
    started: list[int] = []
    completed: list[int] = []

    async def fake_get_task_stages(client: object, group_id: int) -> list[dict[str, Any]]:
        return [
            {"ID": "10", "SORT": "100", "SYSTEM_TYPE": None, "TITLE": "Новая"},
            {"ID": "20", "SORT": "200", "SYSTEM_TYPE": None, "TITLE": "В работе"},
            {"ID": "30", "SORT": "300", "SYSTEM_TYPE": None, "TITLE": "Завершена"},
        ]

    async def fake_move_task_to_stage(client: object, task_id: int, stage_id: int) -> bool:
        moved.append((task_id, stage_id))
        return True

    async def fake_start_task(client: object, task_id: int) -> None:
        started.append(task_id)

    async def fake_complete_task(client: object, task_id: int) -> None:
        completed.append(task_id)

    async def fake_find_task_by_title(client: object, group_id: int, title: str) -> Optional[int]:
        return None

    async def fake_add_task_comment(client: object, task_id: int, message: str) -> int:
        return 1

    monkeypatch.setattr(webhook_handler, "_get_list_context", fake_get_list_context)
    monkeypatch.setattr(webhook_handler.lists, "get_elements", fake_get_elements)
    monkeypatch.setattr(webhook_handler.lists, "update_element", fake_update_element)
    monkeypatch.setattr(webhook_handler.tasks_methods, "get_task_stages", fake_get_task_stages)
    monkeypatch.setattr(webhook_handler.tasks_methods, "move_task_to_stage", fake_move_task_to_stage)
    monkeypatch.setattr(webhook_handler.tasks_methods, "start_task", fake_start_task)
    monkeypatch.setattr(webhook_handler.tasks_methods, "complete_task", fake_complete_task)
    monkeypatch.setattr(webhook_handler.tasks_methods, "find_task_by_title", fake_find_task_by_title)
    monkeypatch.setattr(webhook_handler.tasks_methods, "add_task_comment", fake_add_task_comment)

    await webhook_handler._update_subtask_progress(
        client=object(),
        project_id=42,
        task_etap="Этап 1",
        task_zadacha="Задача 1",
        subtask_updates=[{"element_id": 101, "status": update_status}],
        comment="",
    )

    assert moved == [(900, expected_stage_id)]
    if expect_complete:
        assert completed == [900]
        assert started == []
    else:
        assert started == [900]
        assert completed == []


@pytest.mark.asyncio
async def test_update_subtask_progress_moves_parent_to_progress_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When any subtask is started, parent should move to progress stage + start."""
    await _run_parent_kanban_progress_case(
        monkeypatch=monkeypatch,
        update_status="started",
        expected_stage_id=20,
        expect_complete=False,
    )


@pytest.mark.asyncio
async def test_update_subtask_progress_moves_parent_to_finish_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When all subtasks are done, parent should move to finish stage + complete."""
    await _run_parent_kanban_progress_case(
        monkeypatch=monkeypatch,
        update_status="done",
        expected_stage_id=30,
        expect_complete=True,
    )
