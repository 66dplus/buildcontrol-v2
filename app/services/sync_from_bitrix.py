"""
Reverse-sync: walk Bitrix24 workgroups → find 5 BuildControl lists → write SQLite.

Idempotent: calling sync_all_projects multiple times produces the same result.
Projects already in SQLite are updated; child rows are deleted and re-inserted.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from bitrix.client import BitrixClient
from bitrix.methods import lists as bx_lists
from bitrix.methods import workgroups as bx_workgroups
from bitrix.methods import tasks as bx_tasks
from config import settings
from db import repo

logger = logging.getLogger(__name__)

# Keywords to match each of the 5 BuildControl lists (case-insensitive partial)
_LIST_KEYWORDS = ["бюджет", "задач", "материал", "трудозатрат", "техник"]


# ---------------------------------------------------------------------------
# Helpers copied minimally from ExcelImporter (no openpyxl dep here)
# ---------------------------------------------------------------------------

def _fval(raw: Any) -> float:
    """Convert a raw Bitrix24 property string to float. Handles '1 234,56' → 1234.56."""
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s:
        return 0.0
    # Remove thousands separators (space or non-breaking space) and replace comma decimal
    s = s.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _sval(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def _kw(keys: List[str], *keywords: str) -> Optional[str]:
    """Return first key containing ALL keyword strings (case-insensitive)."""
    for k in keys:
        kl = k.lower()
        if all(w in kl for w in keywords):
            return k
    return None


def _prop(element: Dict[str, Any], prop_id: int) -> Any:
    """Extract raw value from PROPERTY_XX dict or plain string."""
    raw = element.get(f"PROPERTY_{prop_id}")
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = next(iter(raw.values()), None)
    return raw


def _fv(element: Dict[str, Any], prop_id: Optional[int]) -> float:
    if prop_id is None:
        return 0.0
    return _fval(_prop(element, prop_id))


def _sv(element: Dict[str, Any], prop_id: Optional[int]) -> str:
    if prop_id is None:
        return ""
    return _sval(_prop(element, prop_id))


def _resolve(field_map: Dict[str, int], *keywords: str) -> Optional[int]:
    """Find prop ID whose field name contains ALL keywords (case-insensitive)."""
    for fname, pid in field_map.items():
        fl = fname.lower()
        if all(kw in fl for kw in keywords):
            return pid
    return None


# ---------------------------------------------------------------------------
# Main sync function
# ---------------------------------------------------------------------------

async def sync_all_projects(conn: aiosqlite.Connection) -> Dict[str, Any]:
    """
    Walk every active Bitrix24 workgroup, find 5 BuildControl lists, write SQLite.

    Returns:
        {"projects": int, "phases": int, "tasks": int,
         "materials": int, "labor": int, "equipment": int, "skipped": [str]}
    """
    counts: Dict[str, Any] = {
        "projects": 0,
        "phases": 0,
        "tasks": 0,
        "materials": 0,
        "labor": 0,
        "equipment": 0,
        "skipped": [],
    }

    async with BitrixClient() as client:
        groups = await bx_workgroups.list_projects(client)
        logger.info("INFO sync: found %d workgroups", len(groups))

        for g in groups:
            project_id = int(g["id"])
            project_name = g["name"]
            try:
                result = await _sync_one_project(client, conn, project_id, project_name)
                counts["projects"] += 1
                counts["phases"] += result["phases"]
                counts["tasks"] += result["tasks"]
                counts["materials"] += result["materials"]
                counts["labor"] += result["labor"]
                counts["equipment"] += result["equipment"]
                logger.info(
                    "INFO sync: project %d '%s' — phases=%d tasks=%d mat=%d lab=%d eq=%d",
                    project_id, project_name,
                    result["phases"], result["tasks"],
                    result["materials"], result["labor"], result["equipment"],
                )
            except _SkipProject as exc:
                counts["skipped"].append(f"{project_name} ({exc})")
                logger.info("INFO sync: skipping '%s' — %s", project_name, exc)
            except Exception as exc:
                counts["skipped"].append(f"{project_name} (error: {exc})")
                logger.warning("WARN sync: error syncing '%s': %s", project_name, exc)

    logger.info(
        "INFO sync: done — projects=%d phases=%d tasks=%d mat=%d lab=%d eq=%d skipped=%d",
        counts["projects"], counts["phases"], counts["tasks"],
        counts["materials"], counts["labor"], counts["equipment"],
        len(counts["skipped"]),
    )
    return counts


class _SkipProject(Exception):
    """Signal that a workgroup lacks the required BuildControl lists."""


async def _sync_one_project(
    client: BitrixClient,
    conn: aiosqlite.Connection,
    project_id: int,
    project_name: str,
) -> Dict[str, int]:
    """Sync a single workgroup into SQLite. Raises _SkipProject if lists are missing."""

    all_lists = await bx_lists.get_lists(client, project_id)

    # Locate each of the 5 required lists
    found: Dict[str, Dict[str, Any]] = {}
    for kw in _LIST_KEYWORDS:
        lst = bx_lists.find_list_by_keyword(all_lists, kw)
        if lst is None:
            raise _SkipProject(f"missing list keyword='{kw}'")
        found[kw] = lst

    budget_lst   = found["бюджет"]
    zadach_lst   = found["задач"]
    material_lst = found["материал"]
    labor_lst    = found["трудозатрат"]
    equip_lst    = found["техник"]

    # Upsert the project row first
    await repo.upsert_project(conn, project_id, project_name)

    result = {"phases": 0, "tasks": 0, "materials": 0, "labor": 0, "equipment": 0}

    # ---- 1. Бюджет ----
    phases_count = await _sync_budget(client, conn, project_id, budget_lst)
    result["phases"] = phases_count

    # ---- 2. Этапы и задачи ----
    tasks_count, task_name_to_btask = await _sync_tasks(
        client, conn, project_id, project_name, zadach_lst
    )
    result["tasks"] = tasks_count

    # ---- 3. Материалы ----
    result["materials"] = await _sync_materials(client, conn, project_id, material_lst)

    # ---- 4. Трудозатраты ----
    result["labor"] = await _sync_labor(client, conn, project_id, labor_lst)

    # ---- 5. Техника ----
    result["equipment"] = await _sync_equipment(client, conn, project_id, equip_lst)

    return result


async def _get_list_data(
    client: BitrixClient,
    lst: Dict[str, Any],
    group_id: int,
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """Fetch field map + elements for a list. Returns (field_map, elements)."""
    list_id = int(lst["ID"])
    iblock_code = lst.get("IBLOCK_CODE", "")
    fields_resp = await bx_lists.get_fields(client, list_id, iblock_code, group_id)
    field_map = bx_lists.resolve_field_map(fields_resp)
    elements = await bx_lists.get_elements(client, list_id, iblock_code, group_id)
    return field_map, elements


async def _sync_budget(
    client: BitrixClient,
    conn: aiosqlite.Connection,
    project_id: int,
    lst: Dict[str, Any],
) -> int:
    field_map, elements = await _get_list_data(client, lst, project_id)

    mat_p_id  = _resolve(field_map, "материал", "план")
    lab_p_id  = _resolve(field_map, "фот", "план")
    eq_p_id   = _resolve(field_map, "техник", "план")
    tot_p_id  = _resolve(field_map, "итого", "план")
    mat_a_id  = _resolve(field_map, "материал", "факт")
    lab_a_id  = _resolve(field_map, "фот", "факт")
    eq_a_id   = _resolve(field_map, "техник", "факт")
    tot_a_id  = _resolve(field_map, "итого", "факт")

    count = 0
    for elem in elements:
        phase_name = _sval(elem.get("NAME", ""))
        if not phase_name or "итого" in phase_name.lower():
            continue
        mat_p = _fv(elem, mat_p_id)
        lab_p = _fv(elem, lab_p_id)
        eq_p  = _fv(elem, eq_p_id)
        tot_p = _fv(elem, tot_p_id) or (mat_p + lab_p + eq_p)
        await repo.upsert_budget_phase(
            conn, project_id, phase_name,
            bitrix_element_id=str(elem.get("ID", "")),
            materials_plan=mat_p,
            labor_plan=lab_p,
            equipment_plan=eq_p,
            total_plan=tot_p,
            materials_actual=_fv(elem, mat_a_id),
            labor_actual=_fv(elem, lab_a_id),
            equipment_actual=_fv(elem, eq_a_id),
            total_actual=_fv(elem, tot_a_id),
        )
        count += 1
    return count


async def _sync_tasks(
    client: BitrixClient,
    conn: aiosqlite.Connection,
    project_id: int,
    project_name: str,
    lst: Dict[str, Any],
) -> Tuple[int, Dict[Tuple[str, str], str]]:
    """
    Sync "2. Этапы и задачи" list.

    Returns (count, task_name_map) where task_name_map maps
    (phase.lower(), task_name.lower()) → bitrix_task_id_str.
    """
    field_map, elements = await _get_list_data(client, lst, project_id)

    etap_id       = _resolve(field_map, "этап")
    start_p_id    = _resolve(field_map, "нач", "план")
    end_p_id      = _resolve(field_map, "ок.", "план") or _resolve(field_map, "окон", "план")
    budget_p_id   = _resolve(field_map, "бюджет", "план")
    budget_a_id   = _resolve(field_map, "бюджет", "факт")
    start_a_id    = _resolve(field_map, "нач", "факт")
    end_a_id      = _resolve(field_map, "ок.", "факт") or _resolve(field_map, "окон", "факт")
    pct_a_id      = _resolve(field_map, "готовн. факт") or _resolve(field_map, "готовн", "факт")
    btask_id_pid  = _resolve(field_map, "bitrix task id") or _resolve(field_map, "bitrix")

    task_name_map: Dict[Tuple[str, str], str] = {}
    count = 0

    for elem in elements:
        task_name = _sval(elem.get("NAME", ""))
        phase = _sv(elem, etap_id)
        if not task_name or not phase or "итого" in task_name.lower():
            continue

        bitrix_task_id: Optional[str] = None
        if btask_id_pid is not None:
            raw_btask = _prop(elem, btask_id_pid)
            if raw_btask:
                s = str(raw_btask).strip()
                if s:
                    bitrix_task_id = s
                    task_name_map[(phase.lower(), task_name.lower())] = s

        await repo.upsert_task(
            conn, project_id, phase, task_name,
            bitrix_task_id=bitrix_task_id,
            bitrix_element_id=str(elem.get("ID", "")),
            date_start_plan=_sv(elem, start_p_id) or None,
            date_end_plan=_sv(elem, end_p_id) or None,
            date_start_actual=_sv(elem, start_a_id) or None,
            date_end_actual=_sv(elem, end_a_id) or None,
            budget_plan=_fv(elem, budget_p_id),
            budget_actual=_fv(elem, budget_a_id),
            completion_pct=_fv(elem, pct_a_id),
        )
        count += 1

    return count, task_name_map


async def _sync_materials(
    client: BitrixClient,
    conn: aiosqlite.Connection,
    project_id: int,
    lst: Dict[str, Any],
) -> int:
    field_map, elements = await _get_list_data(client, lst, project_id)

    etap_id   = _resolve(field_map, "этап")
    task_id   = _resolve(field_map, "задача")
    unit_id   = _resolve(field_map, "ед.")
    pp_id     = _resolve(field_map, "цена", "план")
    qp_id     = _resolve(field_map, "объём", "план")
    cp_id     = _resolve(field_map, "стоим", "план")
    pa_id     = _resolve(field_map, "цена", "факт")
    qb_id     = _resolve(field_map, "куплено")
    qi_id     = _resolve(field_map, "израсход")
    qs_id     = _resolve(field_map, "остаток")
    ca_id     = _resolve(field_map, "стоим", "факт")

    count = 0
    for elem in elements:
        mat_name = _sval(elem.get("NAME", ""))
        phase    = _sv(elem, etap_id)
        task     = _sv(elem, task_id)
        if not mat_name or not phase or not task or "итого" in mat_name.lower():
            continue
        await repo.upsert_material(
            conn, project_id, phase, task, mat_name,
            bitrix_element_id=str(elem.get("ID", "")),
            unit=_sv(elem, unit_id),
            price_plan=_fv(elem, pp_id),
            qty_plan=_fv(elem, qp_id),
            cost_plan=_fv(elem, cp_id),
            price_actual=_fv(elem, pa_id),
            qty_bought=_fv(elem, qb_id),
            qty_consumed=_fv(elem, qi_id),
            qty_stock=_fv(elem, qs_id),
            cost_actual=_fv(elem, ca_id),
        )
        count += 1
    return count


async def _sync_labor(
    client: BitrixClient,
    conn: aiosqlite.Connection,
    project_id: int,
    lst: Dict[str, Any],
) -> int:
    field_map, elements = await _get_list_data(client, lst, project_id)

    etap_id    = _resolve(field_map, "этап")
    task_id    = _resolve(field_map, "задача")
    rate_id    = _resolve(field_map, "ставка")
    hp_id      = _resolve(field_map, "ч-часов", "план") or _resolve(field_map, "часов", "план")
    pp_id      = _resolve(field_map, "фот", "план")
    ha_id      = _resolve(field_map, "ч-часов", "факт") or _resolve(field_map, "часов", "факт")
    pa_id      = _resolve(field_map, "фот", "факт")

    count = 0
    for elem in elements:
        spec   = _sval(elem.get("NAME", ""))
        phase  = _sv(elem, etap_id)
        task   = _sv(elem, task_id)
        if not spec or not phase or not task or "итого" in spec.lower():
            continue
        await repo.upsert_labor(
            conn, project_id, phase, task, spec,
            bitrix_element_id=str(elem.get("ID", "")),
            rate=_fv(elem, rate_id),
            hours_plan=_fv(elem, hp_id),
            payroll_plan=_fv(elem, pp_id),
            hours_actual=_fv(elem, ha_id),
            payroll_actual=_fv(elem, pa_id),
        )
        count += 1
    return count


async def _sync_equipment(
    client: BitrixClient,
    conn: aiosqlite.Connection,
    project_id: int,
    lst: Dict[str, Any],
) -> int:
    field_map, elements = await _get_list_data(client, lst, project_id)

    etap_id  = _resolve(field_map, "этап")
    task_id  = _resolve(field_map, "задача")
    price_id = _resolve(field_map, "цена")
    hp_id    = _resolve(field_map, "часов", "план")
    tp_id    = _resolve(field_map, "итого", "план")
    ha_id    = _resolve(field_map, "часов", "факт")
    ta_id    = _resolve(field_map, "итого", "факт")

    count = 0
    for elem in elements:
        eq_name = _sval(elem.get("NAME", ""))
        phase   = _sv(elem, etap_id)
        task    = _sv(elem, task_id)
        if not eq_name or not phase or not task or "итого" in eq_name.lower():
            continue
        hours_plan = _fv(elem, hp_id)
        price_ph   = _fv(elem, price_id)
        total_p    = _fv(elem, tp_id) or (hours_plan * price_ph)
        await repo.upsert_equipment(
            conn, project_id, phase, task, eq_name,
            bitrix_element_id=str(elem.get("ID", "")),
            price_per_hour=price_ph,
            hours_plan=hours_plan,
            total_plan=total_p,
            hours_actual=_fv(elem, ha_id),
            total_actual=_fv(elem, ta_id),
        )
        count += 1
    return count
