"""
Cascade update logic for v3 hierarchy: Resources → Tasks → Budget.

New architecture:
  1. Aggregation is done via SQLite SUM queries (fast, no Bitrix rate-limit).
  2. SQLite is updated with the new totals.
  3. The result is mirrored back to Bitrix so the director's native list view stays current.

Bitrix calls reduced: from 7–10 per cascade to 3 (task list meta + element find + element update).
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from bitrix.client import BitrixClient
from bitrix.methods import lists
from db.database import get_db
from db import repo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: Bitrix write-back helpers (kept for director's native list view)
# ---------------------------------------------------------------------------

async def _bitrix_list_context(
    client: BitrixClient,
    project_id: int,
    keyword: str,
) -> Optional[Tuple[int, str, Dict[str, int], List[Dict[str, Any]]]]:
    """Return (list_id, iblock_code, field_map, elements) for a list by keyword."""
    all_lists = await lists.get_lists(client, project_id)
    target = lists.find_list_by_keyword(all_lists, keyword)
    if not target:
        return None
    list_id = int(target["ID"])
    iblock_code = target.get("IBLOCK_CODE", "")
    fields_resp = await lists.get_fields(client, list_id, iblock_code, project_id)
    field_map = lists.resolve_field_map(fields_resp)
    elements = await lists.get_elements(client, list_id, iblock_code, project_id)
    return list_id, iblock_code, field_map, elements


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def cascade_update_task(
    client: BitrixClient,
    project_id: int,
    etap: str,
    zadacha: str,
) -> bool:
    """
    Recompute Бюджет факт for one task.

    - Aggregation: SQLite SUM (instant).
    - SQLite update: sets tasks.budget_actual.
    - Bitrix mirror: writes Бюджет факт back to "2. Этапы и задачи" list element.
    """
    # 1. Aggregate from SQLite
    async with get_db() as conn:
        total_fact = await repo.cascade_task_budget(conn, project_id, etap, zadacha)

    logger.info(
        "Cascade task SQLite: project=%d etap='%s' zadacha='%s' total=%.2f",
        project_id, etap, zadacha, total_fact,
    )

    # 2. Mirror to Bitrix (best-effort — failure doesn't break the report flow)
    try:
        task_ctx = await _bitrix_list_context(client, project_id, "задач")
        if not task_ctx:
            logger.warning("Cascade: Tasks list not found for project %d", project_id)
            return True  # SQLite is updated; Bitrix mirror failed but that's ok

        task_list_id, task_iblock, task_fm, task_elems = task_ctx
        filters = {"Этап": etap, "Задача": zadacha}
        matched = lists.find_elements_by_properties(task_elems, task_fm, filters)
        if not matched:
            logger.warning("Cascade: Task not found for Этап='%s', Задача='%s'", etap, zadacha)
            return True

        task_elem = matched[0]
        task_id = int(task_elem["ID"])
        task_name = task_elem.get("NAME", zadacha)
        pid_budget_fact = lists._resolve_filter_pid(task_fm, "бюджет факт")
        if not pid_budget_fact:
            logger.warning("Cascade: 'Бюджет факт' field not found in tasks list")
            return True

        merged = lists.extract_all_prop_values(task_elem)
        merged[pid_budget_fact] = round(total_fact, 2)
        await lists.update_element(client, task_list_id, task_iblock, project_id, task_id, merged, name=task_name)
        logger.info("Cascade: Bitrix task mirror OK — '%s' Бюджет факт=%.2f", zadacha, total_fact)
    except Exception as exc:
        logger.warning("Cascade: Bitrix task mirror failed (SQLite is correct): %s", exc)

    return True


async def cascade_update_budget(
    client: BitrixClient,
    project_id: int,
    etap: str,
) -> bool:
    """
    Recompute fact columns for a phase in "1. Бюджет".

    - Aggregation: SQLite SUM (instant).
    - SQLite update: sets budget_phases.*_actual.
    - Bitrix mirror: writes Материалы/ФОТ/Техника/Итого факт back to "1. Бюджет" element.
    """
    # 1. Aggregate + update SQLite
    async with get_db() as conn:
        totals = await repo.cascade_phase_budget(conn, project_id, etap)

    mat_fact   = totals["materials_actual"]
    lab_fact   = totals["labor_actual"]
    eq_fact    = totals["equipment_actual"]
    total_fact = totals["total_actual"]

    logger.info(
        "Cascade budget SQLite: project=%d etap='%s' mat=%.2f lab=%.2f eq=%.2f total=%.2f",
        project_id, etap, mat_fact, lab_fact, eq_fact, total_fact,
    )

    # 2. Mirror to Bitrix (best-effort)
    try:
        budget_ctx = await _bitrix_list_context(client, project_id, "бюджет")
        if not budget_ctx:
            logger.warning("Cascade: Budget list not found for project %d", project_id)
            return True

        budget_list_id, budget_iblock, budget_fm, budget_elems = budget_ctx
        budget_elem = lists.find_element_by_name(budget_elems, etap)
        if not budget_elem:
            logger.warning("Cascade: Budget row not found for Этап='%s'", etap)
            return True

        budget_id   = int(budget_elem["ID"])
        budget_name = budget_elem.get("NAME", etap)
        merged = lists.extract_all_prop_values(budget_elem)

        pid_mat   = lists._resolve_filter_pid(budget_fm, "материалы факт")
        pid_fot   = lists._resolve_filter_pid(budget_fm, "фот факт")
        pid_tech  = lists._resolve_filter_pid(budget_fm, "техника факт")
        pid_total = lists._resolve_filter_pid(budget_fm, "итого факт")

        if pid_mat:   merged[pid_mat]   = round(mat_fact,   2)
        if pid_fot:   merged[pid_fot]   = round(lab_fact,   2)
        if pid_tech:  merged[pid_tech]  = round(eq_fact,    2)
        if pid_total: merged[pid_total] = round(total_fact, 2)

        await lists.update_element(client, budget_list_id, budget_iblock, project_id, budget_id, merged, name=budget_name)
        logger.info("Cascade: Bitrix budget mirror OK — '%s' Итого=%.2f", etap, total_fact)
    except Exception as exc:
        logger.warning("Cascade: Bitrix budget mirror failed (SQLite is correct): %s", exc)

    return True
