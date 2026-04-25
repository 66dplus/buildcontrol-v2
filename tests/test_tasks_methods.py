"""Tests for tasks methods wrappers."""

import pytest

from bitrix.methods import tasks


class DummyClient:
    """Simple async Bitrix client stub."""

    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_create_task_sets_planned_range_and_deadline() -> None:
    """create_task should pass START_DATE_PLAN + END_DATE_PLAN and sync DEADLINE."""
    client = DummyClient([{"result": {"task": {"id": 123}}}])

    task_id = await tasks.create_task(
        client,
        title="Test task",
        start_date_plan="2026-05-01",
        end_date_plan="2026-05-15",
        group_id=10,
    )

    assert task_id == 123
    method, params = client.calls[0]
    fields = params["fields"]
    assert method == "tasks.task.add"
    assert fields["START_DATE_PLAN"] == "2026-05-01"
    assert fields["END_DATE_PLAN"] == "2026-05-15"
    assert fields["DEADLINE"] == "2026-05-15"


@pytest.mark.asyncio
async def test_create_subtask_derives_end_date_plan_from_deadline() -> None:
    """create_subtask should send END_DATE_PLAN when only start+deadline is provided."""
    client = DummyClient([{"result": {"task": {"id": 456}}}])

    subtask_id = await tasks.create_subtask(
        client,
        parent_id=111,
        title="Child task",
        start_date_plan="2026-06-01",
        deadline="2026-06-03",
        group_id=10,
    )

    assert subtask_id == 456
    method, params = client.calls[0]
    fields = params["fields"]
    assert method == "tasks.task.add"
    assert fields["START_DATE_PLAN"] == "2026-06-01"
    assert fields["END_DATE_PLAN"] == "2026-06-03"
    assert fields["DEADLINE"] == "2026-06-03"


@pytest.mark.asyncio
async def test_list_root_task_ids_uses_only_root_filter_with_pagination() -> None:
    """list_root_task_ids should paginate and parse both id/ID key formats."""
    client = DummyClient([
        {
            "result": {
                "tasks": [
                    {"id": "1"},
                    {"id": "2"},
                ],
            },
            "next": 50,
        },
        {
            "result": [
                {"ID": "3"},
            ],
        },
    ])

    root_ids = await tasks.list_root_task_ids(client, group_id=77)

    assert root_ids == {1, 2, 3}
    first_call_method, first_call_params = client.calls[0]
    assert first_call_method == "tasks.task.list"
    assert first_call_params["filter"]["ONLY_ROOT_TASKS"] == "Y"
