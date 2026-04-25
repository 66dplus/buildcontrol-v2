"""Tests for Universal List keyword matching helpers."""

from bitrix.methods import lists


def test_list_name_matches_excludes_subtasks_for_tasks_keyword() -> None:
    """Keyword 'задач' must not match 'Подзадачи' list names."""
    assert lists.list_name_matches("2. Этапы и задачи", "задач")
    assert not lists.list_name_matches("6. Подзадачи", "задач")


def test_find_list_by_keyword_skips_subtasks_for_tasks_keyword() -> None:
    """When both lists exist, root tasks list should be selected."""
    all_lists = [
        {"ID": "99", "NAME": "6. Подзадачи", "IBLOCK_CODE": "podzadachi"},
        {"ID": "42", "NAME": "2. Этапы и задачи", "IBLOCK_CODE": "zadachi"},
    ]

    found = lists.find_list_by_keyword(all_lists, "задач")

    assert found is not None
    assert found["ID"] == "42"
