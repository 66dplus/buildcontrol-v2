"""
Cascade update logic for v3 hierarchy: Resources → Tasks → Budget.

When a Level-3 list (materials/labor/equipment) is updated, this module
recomputes the parent Task row and grandparent Budget row by summing
all children — full recompute, not incremental.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from bitrix.client import BitrixClient
from bitrix.methods import lists

logger = logging.getLogger(__name__)


async def _get_list_context(
    client: BitrixClient,
    project_id: int,
    name_keyword: str,
) -> Optional[Tuple[int, str, Dict[str, int], List[Dict[str, Any]]]]:
    """Find a list by name keyword and return (list_id, iblock_code, field_map, elements)."""
    all_lists = await lists.get_lists(client, project_id)
    target = lists.find_list_by_keyword(all_lists, name_keyword)
    if target:
        list_id = int(target["ID"])
        iblock_code = target.get("IBLOCK_CODE", "")
        fields_resp = await lists.get_fields(client, list_id, iblock_code, project_id)
        field_map = lists.resolve_field_map(fields_resp)
        elements = await lists.get_elements(client, list_id, iblock_code, project_id)
        return list_id, iblock_code, field_map, elements
    return None


async def cascade_update_task(
    client: BitrixClient,
    project_id: int,
    etap: str,
    zadacha: str,
) -> bool:
    """
    Recompute Бюджет факт for a specific task in "2. Этапы и задачи".

    Sums fact values from materials, labor, and equipment for the given
    (Этап, Задача) pair and writes the total to the task's Бюджет факт field.

    Returns True on success, False if task list/element not found.
    """
    filters = {"Этап": etap, "Задача": zadacha}

    # --- Sum materials fact ---
    materials_fact = 0.0
    mat_ctx = await _get_list_context(client, project_id, "материал")
    if mat_ctx:
        _, _, mat_fm, mat_elems = mat_ctx
        matched = lists.find_elements_by_properties(mat_elems, mat_fm, filters)
        materials_fact = lists.sum_prop_values(matched, mat_fm, "стоим. факт")

    # --- Sum labor fact ---
    labor_fact = 0.0
    lab_ctx = await _get_list_context(client, project_id, "трудозатрат")
    if lab_ctx:
        _, _, lab_fm, lab_elems = lab_ctx
        matched = lists.find_elements_by_properties(lab_elems, lab_fm, filters)
        labor_fact = lists.sum_prop_values(matched, lab_fm, "фот факт")

    # --- Sum equipment fact ---
    equip_fact = 0.0
    eq_ctx = await _get_list_context(client, project_id, "техник")
    if eq_ctx:
        _, _, eq_fm, eq_elems = eq_ctx
        matched = lists.find_elements_by_properties(eq_elems, eq_fm, filters)
        equip_fact = lists.sum_prop_values(matched, eq_fm, "итого факт")

    total_fact = materials_fact + labor_fact + equip_fact

    # --- Find and update the task element ---
    task_ctx = await _get_list_context(client, project_id, "задач")
    if not task_ctx:
        logger.warning(f"Cascade: Tasks list not found for project {project_id}")
        return False
    task_list_id, task_iblock, task_fm, task_elems = task_ctx

    matched_tasks = lists.find_elements_by_properties(task_elems, task_fm, filters)
    if not matched_tasks:
        logger.warning(f"Cascade: Task not found for Этап='{etap}', Задача='{zadacha}'")
        return False

    task_elem = matched_tasks[0]
    task_id = int(task_elem["ID"])
    task_name = task_elem.get("NAME", zadacha)

    # Find pid for "Бюджет факт"
    pid_budget_fact = lists._resolve_filter_pid(task_fm, "бюджет факт")
    if not pid_budget_fact:
        logger.warning(f"Cascade: 'Бюджет факт' field not found in tasks list")
        return False

    merged = lists.extract_all_prop_values(task_elem)
    merged[pid_budget_fact] = round(total_fact, 2)

    await lists.update_element(
        client, task_list_id, task_iblock, project_id, task_id, merged, name=task_name,
    )
    logger.info(
        f"Cascade: Updated task '{zadacha}' (Этап='{etap}'): "
        f"Бюджет факт={total_fact:.2f} (мат={materials_fact:.2f} + фот={labor_fact:.2f} + техн={equip_fact:.2f})"
    )
    return True


async def cascade_update_budget(
    client: BitrixClient,
    project_id: int,
    etap: str,
) -> bool:
    """
    Recompute fact columns for a phase in "1. Бюджет".

    Sums fact values from materials, labor, and equipment for the given Этап
    and writes Материалы факт, ФОТ факт, Техника факт, Итого факт.

    Returns True on success, False if budget list/element not found.
    """
    etap_filter = {"Этап": etap}

    # --- Sum materials fact ---
    materials_fact = 0.0
    mat_ctx = await _get_list_context(client, project_id, "материал")
    if mat_ctx:
        _, _, mat_fm, mat_elems = mat_ctx
        matched = lists.find_elements_by_properties(mat_elems, mat_fm, etap_filter)
        materials_fact = lists.sum_prop_values(matched, mat_fm, "стоим. факт")

    # --- Sum labor fact ---
    labor_fact = 0.0
    lab_ctx = await _get_list_context(client, project_id, "трудозатрат")
    if lab_ctx:
        _, _, lab_fm, lab_elems = lab_ctx
        matched = lists.find_elements_by_properties(lab_elems, lab_fm, etap_filter)
        labor_fact = lists.sum_prop_values(matched, lab_fm, "фот факт")

    # --- Sum equipment fact ---
    equip_fact = 0.0
    eq_ctx = await _get_list_context(client, project_id, "техник")
    if eq_ctx:
        _, _, eq_fm, eq_elems = eq_ctx
        matched = lists.find_elements_by_properties(eq_elems, eq_fm, etap_filter)
        equip_fact = lists.sum_prop_values(matched, eq_fm, "итого факт")

    # --- Find and update the budget element ---
    budget_ctx = await _get_list_context(client, project_id, "бюджет")
    if not budget_ctx:
        logger.warning(f"Cascade: Budget list not found for project {project_id}")
        return False
    budget_list_id, budget_iblock, budget_fm, budget_elems = budget_ctx

    # Budget row NAME = Этап value (first column)
    budget_elem = lists.find_element_by_name(budget_elems, etap)
    if not budget_elem:
        logger.warning(f"Cascade: Budget row not found for Этап='{etap}'")
        return False

    budget_id = int(budget_elem["ID"])
    budget_name = budget_elem.get("NAME", etap)

    # Resolve PIDs for fact columns
    pid_mat_fact = lists._resolve_filter_pid(budget_fm, "материалы факт")
    pid_fot_fact = lists._resolve_filter_pid(budget_fm, "фот факт")
    pid_tech_fact = lists._resolve_filter_pid(budget_fm, "техника факт")
    pid_total_fact = lists._resolve_filter_pid(budget_fm, "итого факт")

    merged = lists.extract_all_prop_values(budget_elem)

    if pid_mat_fact:
        merged[pid_mat_fact] = round(materials_fact, 2)
    if pid_fot_fact:
        merged[pid_fot_fact] = round(labor_fact, 2)
    if pid_tech_fact:
        merged[pid_tech_fact] = round(equip_fact, 2)
    if pid_total_fact:
        merged[pid_total_fact] = round(materials_fact + labor_fact + equip_fact, 2)

    await lists.update_element(
        client, budget_list_id, budget_iblock, project_id, budget_id, merged, name=budget_name,
    )
    logger.info(
        f"Cascade: Updated budget '{etap}': "
        f"Мат={materials_fact:.2f}, ФОТ={labor_fact:.2f}, Техн={equip_fact:.2f}, "
        f"Итого={materials_fact + labor_fact + equip_fact:.2f}"
    )
    return True
