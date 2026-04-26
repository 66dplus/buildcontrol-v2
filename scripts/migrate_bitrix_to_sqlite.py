"""
One-time migration: read all existing Bitrix24 list data and populate SQLite.

Usage (run once after first deploy):
    cd /opt/buildcontrol && venv/bin/python3 scripts/migrate_bitrix_to_sqlite.py

Idempotent: INSERT OR IGNORE / ON CONFLICT DO NOTHING everywhere, safe to re-run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bitrix.client import BitrixClient
from bitrix.methods import lists, workgroups
from db.database import get_db, init_db
from db import repo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("migrate")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fval(elem: dict, field_map: dict, *keywords: str) -> float:
    for kw in keywords:
        pid = lists._resolve_filter_pid(field_map, kw)
        if pid:
            v = lists.get_prop_value(elem, pid)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
    return 0.0


def _sval(elem: dict, field_map: dict, *keywords: str) -> str:
    for kw in keywords:
        pid = lists._resolve_filter_pid(field_map, kw)
        if pid:
            v = lists.get_prop_value_str(elem, pid)
            if v:
                return v
    return ""


def _unit_pid(field_map: dict) -> int | None:
    for name, pid in field_map.items():
        n = name.lower()
        if "цена" not in n and any(kw in n for kw in ["ед. изм", "ед.изм", "единиц", " unit", "unit "]):
            return pid
    return None


def _bought_pid(field_map: dict) -> int | None:
    for name, pid in field_map.items():
        if "куплено" in name.lower() and "объём" in name.lower():
            return pid
    return None


def _price_plan_pid(field_map: dict) -> int | None:
    for name, pid in field_map.items():
        if "цена ед" in name.lower() and "план" in name.lower():
            return pid
    return None


def _price_fact_pid(field_map: dict) -> int | None:
    for name, pid in field_map.items():
        if "цена ед" in name.lower() and "факт" in name.lower():
            return pid
    return None


# ---------------------------------------------------------------------------
# Per-list migrators
# ---------------------------------------------------------------------------

async def _migrate_budget(conn, project_id: int, client: BitrixClient) -> int:
    all_lists = await lists.get_lists(client, project_id)
    target = lists.find_list_by_keyword(all_lists, "бюджет")
    if not target:
        return 0
    list_id = int(target["ID"])
    iblock = target.get("IBLOCK_CODE", "")
    fm = lists.resolve_field_map(await lists.get_fields(client, list_id, iblock, project_id))
    elements = await lists.get_elements(client, list_id, iblock, project_id)
    count = 0
    for elem in elements:
        phase_name = elem.get("NAME", "").strip()
        if not phase_name:
            continue
        mat_p = _fval(elem, fm, "материалы план")
        lab_p = _fval(elem, fm, "фот план")
        eq_p  = _fval(elem, fm, "техника план")
        tot_p = _fval(elem, fm, "итого план") or (mat_p + lab_p + eq_p)
        mat_a = _fval(elem, fm, "материалы факт")
        lab_a = _fval(elem, fm, "фот факт")
        eq_a  = _fval(elem, fm, "техника факт")
        tot_a = _fval(elem, fm, "итого факт") or (mat_a + lab_a + eq_a)
        await repo.upsert_budget_phase(
            conn, project_id, phase_name,
            bitrix_element_id=str(elem.get("ID", "")),
            materials_plan=mat_p, labor_plan=lab_p, equipment_plan=eq_p, total_plan=tot_p,
            materials_actual=mat_a, labor_actual=lab_a, equipment_actual=eq_a, total_actual=tot_a,
        )
        count += 1
    return count


async def _migrate_tasks(conn, project_id: int, client: BitrixClient) -> int:
    all_lists = await lists.get_lists(client, project_id)
    target = lists.find_list_by_keyword(all_lists, "задач")
    if not target:
        return 0
    list_id = int(target["ID"])
    iblock = target.get("IBLOCK_CODE", "")
    fm = lists.resolve_field_map(await lists.get_fields(client, list_id, iblock, project_id))
    elements = await lists.get_elements(client, list_id, iblock, project_id)
    count = 0
    for elem in elements:
        task_name = elem.get("NAME", "").strip()
        if not task_name:
            continue
        phase = _sval(elem, fm, "этап")
        btask_raw = lists.get_prop_value(elem, lists._resolve_filter_pid(fm, "bitrix task id") or 0)
        btask_id = str(int(btask_raw)) if btask_raw else None
        await repo.upsert_task(
            conn, project_id, phase, task_name,
            bitrix_task_id=btask_id,
            bitrix_element_id=str(elem.get("ID", "")),
            date_start_plan=_sval(elem, fm, "нач. план", "нач план"),
            date_end_plan=_sval(elem, fm, "ок. план", "ок план"),
            date_start_actual=_sval(elem, fm, "нач. факт", "нач факт"),
            date_end_actual=_sval(elem, fm, "ок. факт", "ок факт"),
            budget_plan=_fval(elem, fm, "бюджет план"),
            budget_actual=_fval(elem, fm, "бюджет факт"),
            completion_pct=_fval(elem, fm, "готовн. факт", "% выполнения"),
        )
        count += 1
    return count


async def _migrate_materials(conn, project_id: int, client: BitrixClient) -> int:
    all_lists = await lists.get_lists(client, project_id)
    target = lists.find_list_by_keyword(all_lists, "материал")
    if not target:
        return 0
    list_id = int(target["ID"])
    iblock = target.get("IBLOCK_CODE", "")
    fm = lists.resolve_field_map(await lists.get_fields(client, list_id, iblock, project_id))
    elements = await lists.get_elements(client, list_id, iblock, project_id)

    pid_unit = _unit_pid(fm)
    pid_bought = _bought_pid(fm)
    pid_price_plan = _price_plan_pid(fm)
    pid_price_fact = _price_fact_pid(fm)

    count = 0
    for elem in elements:
        mat_name = elem.get("NAME", "").strip()
        if not mat_name:
            continue
        unit = lists.get_prop_value_str(elem, pid_unit) if pid_unit else ""
        qty_bought = float(lists.get_prop_value(elem, pid_bought) or 0) if pid_bought else 0.0
        price_plan = float(lists.get_prop_value(elem, pid_price_plan) or 0) if pid_price_plan else 0.0
        price_actual = float(lists.get_prop_value(elem, pid_price_fact) or 0) if pid_price_fact else 0.0
        qty_plan = _fval(elem, fm, "объём план")
        qty_consumed = _fval(elem, fm, "израсходовано")
        qty_stock = _fval(elem, fm, "остаток")
        cost_plan = _fval(elem, fm, "стоим. план", "стоимость план")
        cost_actual = _fval(elem, fm, "стоим. факт", "стоимость факт")
        phase = _sval(elem, fm, "этап")
        task_name = _sval(elem, fm, "задача")
        await repo.upsert_material(
            conn, project_id, phase, task_name, mat_name,
            bitrix_element_id=str(elem.get("ID", "")),
            unit=unit or "",
            price_plan=price_plan,
            qty_plan=qty_plan,
            cost_plan=cost_plan,
            price_actual=price_actual,
            qty_bought=qty_bought,
            qty_consumed=qty_consumed,
            qty_stock=qty_stock,
            cost_actual=cost_actual,
        )
        count += 1
    return count


async def _migrate_labor(conn, project_id: int, client: BitrixClient) -> int:
    all_lists = await lists.get_lists(client, project_id)
    target = lists.find_list_by_keyword(all_lists, "трудозатрат")
    if not target:
        return 0
    list_id = int(target["ID"])
    iblock = target.get("IBLOCK_CODE", "")
    fm = lists.resolve_field_map(await lists.get_fields(client, list_id, iblock, project_id))
    elements = await lists.get_elements(client, list_id, iblock, project_id)
    count = 0
    for elem in elements:
        specialty = elem.get("NAME", "").strip()
        if not specialty:
            continue
        phase = _sval(elem, fm, "этап")
        task_name = _sval(elem, fm, "задача")
        await repo.upsert_labor(
            conn, project_id, phase, task_name, specialty,
            bitrix_element_id=str(elem.get("ID", "")),
            rate=_fval(elem, fm, "ставка"),
            hours_plan=_fval(elem, fm, "ч-часов план", "часов план"),
            payroll_plan=_fval(elem, fm, "фот план"),
            hours_actual=_fval(elem, fm, "ч-часов факт", "часов факт"),
            payroll_actual=_fval(elem, fm, "фот факт"),
        )
        count += 1
    return count


async def _migrate_equipment(conn, project_id: int, client: BitrixClient) -> int:
    all_lists = await lists.get_lists(client, project_id)
    target = lists.find_list_by_keyword(all_lists, "техник")
    if not target:
        return 0
    list_id = int(target["ID"])
    iblock = target.get("IBLOCK_CODE", "")
    fm = lists.resolve_field_map(await lists.get_fields(client, list_id, iblock, project_id))
    elements = await lists.get_elements(client, list_id, iblock, project_id)
    count = 0
    for elem in elements:
        eq_name = elem.get("NAME", "").strip()
        if not eq_name:
            continue
        phase = _sval(elem, fm, "этап")
        task_name = _sval(elem, fm, "задача")
        await repo.upsert_equipment(
            conn, project_id, phase, task_name, eq_name,
            bitrix_element_id=str(elem.get("ID", "")),
            price_per_hour=_fval(elem, fm, "цена", "ставка"),
            hours_plan=_fval(elem, fm, "часов план"),
            total_plan=_fval(elem, fm, "итого план"),
            hours_actual=_fval(elem, fm, "часов факт"),
            total_actual=_fval(elem, fm, "итого факт"),
        )
        count += 1
    return count


async def _migrate_purchase_requests(conn, project_id: int, client: BitrixClient) -> int:
    try:
        list_info = await lists.get_or_create_purchase_requests_list(client, project_id)
    except Exception as exc:
        logger.debug("No purchase requests list for project %d: %s", project_id, exc)
        return 0
    list_id = int(list_info["list_id"])
    iblock = list_info["iblock_code"]
    elements = await lists.get_elements(client, list_id, iblock, project_id)
    field_ids = list_info["field_ids"]

    from app.purchase_requests import _row_to_request, _sqlite_status_to_display
    STATUS_MAP = {
        "Ожидает": "pending",
        "Подтверждено": "approved",
        "Отклонено": "rejected",
    }

    count = 0
    for elem in elements:
        try:
            decoded = _row_to_request(elem, field_ids)
            req_id = str(decoded["id"])
            status_display = decoded.get("status", "Ожидает")
            status = STATUS_MAP.get(status_display, "pending")
            # INSERT OR IGNORE (purchase_requests has PRIMARY KEY id)
            async with conn.execute(
                "SELECT id FROM purchase_requests WHERE id=?", (req_id,)
            ) as cur:
                exists = await cur.fetchone()
            if exists:
                continue
            await repo.create_purchase_request(
                conn,
                request_id=req_id,
                project_id=project_id,
                items=decoded.get("items", []),
                buyer_comment=decoded.get("comment") or "",
            )
            if status != "pending":
                await repo.update_purchase_request(
                    conn, req_id,
                    status=status,
                    actor=decoded.get("author") or "",
                )
            count += 1
        except Exception as exc:
            logger.warning("PR migration elem %s failed: %s", elem.get("ID"), exc)
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    await init_db()
    logger.info("SQLite initialized")

    async with BitrixClient() as client:
        projects = await workgroups.list_projects(client)
    logger.info("Found %d active projects", len(projects))

    total = {k: 0 for k in ("budget", "tasks", "materials", "labor", "equipment", "requests")}

    for proj in projects:
        gid = int(proj["id"])
        name = proj.get("name", f"Project {gid}")
        logger.info("Migrating project %d: %s", gid, name)

        async with get_db() as conn:
            await repo.upsert_project(conn, gid, name)

        async with BitrixClient() as client:
            async with get_db() as conn:
                try:
                    n = await _migrate_budget(conn, gid, client)
                    total["budget"] += n
                    logger.info("  budget_phases: %d rows", n)
                except Exception as exc:
                    logger.warning("  budget_phases FAILED: %s", exc)

                try:
                    n = await _migrate_tasks(conn, gid, client)
                    total["tasks"] += n
                    logger.info("  tasks: %d rows", n)
                except Exception as exc:
                    logger.warning("  tasks FAILED: %s", exc)

                try:
                    n = await _migrate_materials(conn, gid, client)
                    total["materials"] += n
                    logger.info("  materials: %d rows", n)
                except Exception as exc:
                    logger.warning("  materials FAILED: %s", exc)

                try:
                    n = await _migrate_labor(conn, gid, client)
                    total["labor"] += n
                    logger.info("  labor: %d rows", n)
                except Exception as exc:
                    logger.warning("  labor FAILED: %s", exc)

                try:
                    n = await _migrate_equipment(conn, gid, client)
                    total["equipment"] += n
                    logger.info("  equipment: %d rows", n)
                except Exception as exc:
                    logger.warning("  equipment FAILED: %s", exc)

                try:
                    n = await _migrate_purchase_requests(conn, gid, client)
                    total["requests"] += n
                    logger.info("  purchase_requests: %d rows", n)
                except Exception as exc:
                    logger.warning("  purchase_requests FAILED: %s", exc)

    logger.info("Migration complete: %s", total)


if __name__ == "__main__":
    asyncio.run(main())
