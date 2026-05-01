"""
Repository layer: thin async wrappers around SQLite queries.

All functions accept an open aiosqlite.Connection (from db.database.get_db).
Return plain dicts or lists of dicts — no aiosqlite.Row objects leak out.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(r: aiosqlite.Row) -> Dict[str, Any]:
    return dict(r)


def _rows(rs: list) -> List[Dict[str, Any]]:
    return [dict(r) for r in rs]


def _normalize_date(date_str: Optional[str]) -> Optional[str]:
    """Convert DD.MM.YYYY → YYYY-MM-DD so SQLite date() comparisons work correctly."""
    if not date_str:
        return date_str
    s = date_str.strip()
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        return f"{s[6:]}-{s[3:5]}-{s[:2]}"
    return s


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

async def upsert_project(conn: aiosqlite.Connection, project_id: int, name: str) -> None:
    await conn.execute(
        "INSERT INTO projects(id, name) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name",
        (project_id, name),
    )
    await conn.commit()


async def get_projects(conn: aiosqlite.Connection, archived: bool = False) -> List[Dict[str, Any]]:
    async with conn.execute(
        "SELECT id, name, is_archived FROM projects WHERE is_archived=? ORDER BY name",
        (1 if archived else 0,),
    ) as cur:
        return _rows(await cur.fetchall())


# ---------------------------------------------------------------------------
# Budget phases
# ---------------------------------------------------------------------------

async def upsert_budget_phase(
    conn: aiosqlite.Connection,
    project_id: int,
    phase_name: str,
    *,
    bitrix_element_id: Optional[str] = None,
    materials_plan: float = 0,
    labor_plan: float = 0,
    equipment_plan: float = 0,
    total_plan: float = 0,
    materials_actual: float = 0,
    labor_actual: float = 0,
    equipment_actual: float = 0,
    total_actual: float = 0,
) -> None:
    await conn.execute(
        """
        INSERT INTO budget_phases(
            project_id, phase_name, bitrix_element_id,
            materials_plan, labor_plan, equipment_plan, total_plan,
            materials_actual, labor_actual, equipment_actual, total_actual
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project_id, phase_name) DO UPDATE SET
            bitrix_element_id = COALESCE(excluded.bitrix_element_id, bitrix_element_id),
            materials_plan  = excluded.materials_plan,
            labor_plan      = excluded.labor_plan,
            equipment_plan  = excluded.equipment_plan,
            total_plan      = excluded.total_plan,
            materials_actual = excluded.materials_actual,
            labor_actual    = excluded.labor_actual,
            equipment_actual = excluded.equipment_actual,
            total_actual    = excluded.total_actual
        """,
        (
            project_id, phase_name, bitrix_element_id,
            materials_plan, labor_plan, equipment_plan, total_plan,
            materials_actual, labor_actual, equipment_actual, total_actual,
        ),
    )
    await conn.commit()


async def get_budget_phases(
    conn: aiosqlite.Connection, project_id: int
) -> List[Dict[str, Any]]:
    async with conn.execute(
        "SELECT * FROM budget_phases WHERE project_id=? ORDER BY phase_name",
        (project_id,),
    ) as cur:
        return _rows(await cur.fetchall())


async def update_budget_phase_actuals(
    conn: aiosqlite.Connection,
    project_id: int,
    phase_name: str,
    materials_actual: float,
    labor_actual: float,
    equipment_actual: float,
    total_actual: float,
) -> None:
    await conn.execute(
        """
        UPDATE budget_phases SET
            materials_actual=?, labor_actual=?, equipment_actual=?, total_actual=?
        WHERE project_id=? AND phase_name=?
        """,
        (materials_actual, labor_actual, equipment_actual, total_actual,
         project_id, phase_name),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

async def upsert_task(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    *,
    bitrix_task_id: Optional[str] = None,
    bitrix_element_id: Optional[str] = None,
    date_start_plan: Optional[str] = None,
    date_end_plan: Optional[str] = None,
    date_start_actual: Optional[str] = None,
    date_end_actual: Optional[str] = None,
    budget_plan: float = 0,
    budget_actual: float = 0,
    completion_pct: float = 0,
    stage_id: Optional[str] = None,
    stage_name: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO tasks(
            project_id, phase, task_name,
            bitrix_task_id, bitrix_element_id,
            date_start_plan, date_end_plan, date_start_actual, date_end_actual,
            budget_plan, budget_actual, completion_pct, stage_id, stage_name
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project_id, phase, task_name) DO UPDATE SET
            bitrix_task_id   = COALESCE(excluded.bitrix_task_id,   bitrix_task_id),
            bitrix_element_id= COALESCE(excluded.bitrix_element_id, bitrix_element_id),
            date_start_plan  = COALESCE(excluded.date_start_plan,  date_start_plan),
            date_end_plan    = COALESCE(excluded.date_end_plan,    date_end_plan),
            date_start_actual= COALESCE(excluded.date_start_actual, date_start_actual),
            date_end_actual  = COALESCE(excluded.date_end_actual,  date_end_actual),
            budget_plan      = excluded.budget_plan,
            budget_actual    = excluded.budget_actual,
            completion_pct   = excluded.completion_pct,
            stage_id         = COALESCE(excluded.stage_id,   stage_id),
            stage_name       = COALESCE(excluded.stage_name, stage_name)
        """,
        (
            project_id, phase, task_name,
            bitrix_task_id, bitrix_element_id,
            _normalize_date(date_start_plan), _normalize_date(date_end_plan),
            _normalize_date(date_start_actual), _normalize_date(date_end_actual),
            budget_plan, budget_actual, completion_pct, stage_id, stage_name,
        ),
    )
    await conn.commit()


async def get_tasks(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if phase:
        async with conn.execute(
            "SELECT * FROM tasks WHERE project_id=? AND phase=? ORDER BY phase, task_name",
            (project_id, phase),
        ) as cur:
            return _rows(await cur.fetchall())
    async with conn.execute(
        "SELECT * FROM tasks WHERE project_id=? ORDER BY phase, task_name",
        (project_id,),
    ) as cur:
        return _rows(await cur.fetchall())


async def update_task_progress(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    *,
    completion_pct: Optional[float] = None,
    stage_id: Optional[str] = None,
    stage_name: Optional[str] = None,
    date_start_actual: Optional[str] = None,
    date_end_actual: Optional[str] = None,
) -> None:
    sets = []
    params: list = []
    if completion_pct is not None:
        sets.append("completion_pct=?"); params.append(completion_pct)
    if stage_id is not None:
        sets.append("stage_id=?"); params.append(stage_id)
    if stage_name is not None:
        sets.append("stage_name=?"); params.append(stage_name)
    if date_start_actual is not None:
        sets.append("date_start_actual=?"); params.append(date_start_actual)
    if date_end_actual is not None:
        sets.append("date_end_actual=?"); params.append(date_end_actual)
    if not sets:
        return
    params += [project_id, phase, task_name]
    await conn.execute(
        f"UPDATE tasks SET {', '.join(sets)} WHERE project_id=? AND phase=? AND task_name=?",
        params,
    )
    await conn.commit()


async def update_task_budget_actual(
    conn: aiosqlite.Connection, project_id: int, phase: str, task_name: str, budget_actual: float
) -> None:
    await conn.execute(
        "UPDATE tasks SET budget_actual=? WHERE project_id=? AND phase=? AND task_name=?",
        (budget_actual, project_id, phase, task_name),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

async def upsert_material(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    material_name: str,
    *,
    bitrix_element_id: Optional[str] = None,
    unit: str = "",
    price_plan: float = 0,
    qty_plan: float = 0,
    cost_plan: float = 0,
    price_actual: float = 0,
    qty_bought: float = 0,
    qty_consumed: float = 0,
    qty_stock: float = 0,
    cost_actual: float = 0,
) -> None:
    await conn.execute(
        """
        INSERT INTO materials(
            project_id, phase, task_name, material_name,
            bitrix_element_id, unit, price_plan, qty_plan, cost_plan,
            price_actual, qty_bought, qty_consumed, qty_stock, cost_actual
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project_id, phase, task_name, material_name) DO UPDATE SET
            unit              = excluded.unit,
            price_plan        = excluded.price_plan,
            qty_plan          = excluded.qty_plan,
            cost_plan         = excluded.cost_plan,
            bitrix_element_id = COALESCE(excluded.bitrix_element_id, bitrix_element_id)
        """,
        (
            project_id, phase, task_name, material_name,
            bitrix_element_id, unit, price_plan, qty_plan, cost_plan,
            price_actual, qty_bought, qty_consumed, qty_stock, cost_actual,
        ),
    )
    await conn.commit()


async def get_materials(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: Optional[str] = None,
    task_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    where = "project_id=?"
    params: list = [project_id]
    if phase:
        where += " AND phase=?"
        params.append(phase)
    if task_name:
        where += " AND task_name=?"
        params.append(task_name)
    async with conn.execute(
        f"SELECT * FROM materials WHERE {where} ORDER BY phase, task_name, material_name",
        params,
    ) as cur:
        return _rows(await cur.fetchall())


async def get_materials_for_buyer(
    conn: aiosqlite.Connection,
    project_id: int,
) -> List[Dict[str, Any]]:
    """Return deduplicated materials aggregated across all phases/tasks for the buyer dropdown."""
    async with conn.execute(
        """
        SELECT material_name,
               unit,
               SUM(qty_plan)   AS qty_plan,
               SUM(qty_bought) AS qty_bought,
               AVG(CASE WHEN price_plan > 0 THEN price_plan END) AS price_plan
        FROM materials
        WHERE project_id = ?
        GROUP BY material_name, unit
        ORDER BY material_name
        """,
        [project_id],
    ) as cur:
        return _rows(await cur.fetchall())


async def get_material_row(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    material_name: str,
) -> Optional[Dict[str, Any]]:
    async with conn.execute(
        "SELECT * FROM materials WHERE project_id=? AND phase=? AND task_name=? AND material_name=?",
        (project_id, phase, task_name, material_name),
    ) as cur:
        row = await cur.fetchone()
        return _row(row) if row else None


async def update_material_after_report(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    material_name: str,
    qty_consumed_delta: float,
    cost_actual_delta: float,
) -> None:
    await conn.execute(
        """
        UPDATE materials SET
            qty_consumed = qty_consumed + ?,
            qty_stock    = qty_stock    - ?,
            cost_actual  = cost_actual  + ?
        WHERE project_id=? AND phase=? AND task_name=? AND material_name=?
        """,
        (qty_consumed_delta, qty_consumed_delta, cost_actual_delta,
         project_id, phase, task_name, material_name),
    )
    await conn.commit()


async def update_material_after_purchase(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    material_name: str,
    qty_bought_delta: float,
    new_price_actual: float,
) -> None:
    await conn.execute(
        """
        UPDATE materials SET
            qty_bought   = qty_bought + ?,
            qty_stock    = qty_stock  + ?,
            price_actual = ?
        WHERE project_id=? AND phase=? AND task_name=? AND material_name=?
        """,
        (qty_bought_delta, qty_bought_delta, new_price_actual,
         project_id, phase, task_name, material_name),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Labor
# ---------------------------------------------------------------------------

async def upsert_labor(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    specialty: str,
    *,
    bitrix_element_id: Optional[str] = None,
    rate: float = 0,
    hours_plan: float = 0,
    payroll_plan: float = 0,
    hours_actual: float = 0,
    payroll_actual: float = 0,
) -> None:
    await conn.execute(
        """
        INSERT INTO labor(
            project_id, phase, task_name, specialty,
            bitrix_element_id, rate, hours_plan, payroll_plan,
            hours_actual, payroll_actual
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project_id, phase, task_name, specialty) DO UPDATE SET
            rate              = excluded.rate,
            hours_plan        = excluded.hours_plan,
            payroll_plan      = excluded.payroll_plan,
            bitrix_element_id = COALESCE(excluded.bitrix_element_id, bitrix_element_id)
        """,
        (
            project_id, phase, task_name, specialty,
            bitrix_element_id, rate, hours_plan, payroll_plan,
            hours_actual, payroll_actual,
        ),
    )
    await conn.commit()


async def get_labor(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: Optional[str] = None,
    task_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    where = "project_id=?"
    params: list = [project_id]
    if phase:
        where += " AND phase=?"
        params.append(phase)
    if task_name:
        where += " AND task_name=?"
        params.append(task_name)
    async with conn.execute(
        f"SELECT * FROM labor WHERE {where} ORDER BY phase, task_name, specialty",
        params,
    ) as cur:
        return _rows(await cur.fetchall())


async def get_labor_row(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    specialty: str,
) -> Optional[Dict[str, Any]]:
    async with conn.execute(
        "SELECT * FROM labor WHERE project_id=? AND phase=? AND task_name=? AND specialty=?",
        (project_id, phase, task_name, specialty),
    ) as cur:
        row = await cur.fetchone()
        return _row(row) if row else None


async def update_labor_after_report(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    specialty: str,
    hours_delta: float,
    payroll_delta: float,
) -> None:
    await conn.execute(
        """
        UPDATE labor SET
            hours_actual   = hours_actual   + ?,
            payroll_actual = payroll_actual + ?
        WHERE project_id=? AND phase=? AND task_name=? AND specialty=?
        """,
        (hours_delta, payroll_delta, project_id, phase, task_name, specialty),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------

async def upsert_equipment(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    equipment_name: str,
    *,
    bitrix_element_id: Optional[str] = None,
    price_per_hour: float = 0,
    hours_plan: float = 0,
    total_plan: float = 0,
    hours_actual: float = 0,
    total_actual: float = 0,
) -> None:
    await conn.execute(
        """
        INSERT INTO equipment_items(
            project_id, phase, task_name, equipment_name,
            bitrix_element_id, price_per_hour, hours_plan, total_plan,
            hours_actual, total_actual
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project_id, phase, task_name, equipment_name) DO UPDATE SET
            price_per_hour    = excluded.price_per_hour,
            hours_plan        = excluded.hours_plan,
            total_plan        = excluded.total_plan,
            bitrix_element_id = COALESCE(excluded.bitrix_element_id, bitrix_element_id)
        """,
        (
            project_id, phase, task_name, equipment_name,
            bitrix_element_id, price_per_hour, hours_plan, total_plan,
            hours_actual, total_actual,
        ),
    )
    await conn.commit()


async def get_equipment(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: Optional[str] = None,
    task_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    where = "project_id=?"
    params: list = [project_id]
    if phase:
        where += " AND phase=?"
        params.append(phase)
    if task_name:
        where += " AND task_name=?"
        params.append(task_name)
    async with conn.execute(
        f"SELECT * FROM equipment_items WHERE {where} ORDER BY phase, task_name, equipment_name",
        params,
    ) as cur:
        return _rows(await cur.fetchall())


async def get_equipment_row(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    equipment_name: str,
) -> Optional[Dict[str, Any]]:
    async with conn.execute(
        "SELECT * FROM equipment_items WHERE project_id=? AND phase=? AND task_name=? AND equipment_name=?",
        (project_id, phase, task_name, equipment_name),
    ) as cur:
        row = await cur.fetchone()
        return _row(row) if row else None


async def update_equipment_after_report(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
    equipment_name: str,
    hours_delta: float,
    total_delta: float,
) -> None:
    await conn.execute(
        """
        UPDATE equipment_items SET
            hours_actual = hours_actual + ?,
            total_actual = total_actual + ?
        WHERE project_id=? AND phase=? AND task_name=? AND equipment_name=?
        """,
        (hours_delta, total_delta, project_id, phase, task_name, equipment_name),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Cascade aggregations
# ---------------------------------------------------------------------------

async def cascade_task_budget(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
    task_name: str,
) -> float:
    """Sum cost_actual + payroll_actual + total_actual for task → update tasks.budget_actual."""
    async with conn.execute(
        "SELECT COALESCE(SUM(cost_actual),0) FROM materials WHERE project_id=? AND phase=? AND task_name=?",
        (project_id, phase, task_name),
    ) as cur:
        mat = (await cur.fetchone())[0]
    async with conn.execute(
        "SELECT COALESCE(SUM(payroll_actual),0) FROM labor WHERE project_id=? AND phase=? AND task_name=?",
        (project_id, phase, task_name),
    ) as cur:
        lab = (await cur.fetchone())[0]
    async with conn.execute(
        "SELECT COALESCE(SUM(total_actual),0) FROM equipment_items WHERE project_id=? AND phase=? AND task_name=?",
        (project_id, phase, task_name),
    ) as cur:
        eq = (await cur.fetchone())[0]
    budget_actual = float(mat) + float(lab) + float(eq)
    await conn.execute(
        "UPDATE tasks SET budget_actual=? WHERE project_id=? AND phase=? AND task_name=?",
        (budget_actual, project_id, phase, task_name),
    )
    await conn.commit()
    return budget_actual


async def cascade_phase_budget(
    conn: aiosqlite.Connection,
    project_id: int,
    phase: str,
) -> Dict[str, float]:
    """Sum per-category actuals for phase → update budget_phases. Returns totals dict."""
    async with conn.execute(
        "SELECT COALESCE(SUM(cost_actual),0) FROM materials WHERE project_id=? AND phase=?",
        (project_id, phase),
    ) as cur:
        mat = float((await cur.fetchone())[0])
    async with conn.execute(
        "SELECT COALESCE(SUM(payroll_actual),0) FROM labor WHERE project_id=? AND phase=?",
        (project_id, phase),
    ) as cur:
        lab = float((await cur.fetchone())[0])
    async with conn.execute(
        "SELECT COALESCE(SUM(total_actual),0) FROM equipment_items WHERE project_id=? AND phase=?",
        (project_id, phase),
    ) as cur:
        eq = float((await cur.fetchone())[0])
    total = mat + lab + eq
    await conn.execute(
        """
        UPDATE budget_phases SET
            materials_actual=?, labor_actual=?, equipment_actual=?, total_actual=?
        WHERE project_id=? AND phase_name=?
        """,
        (mat, lab, eq, total, project_id, phase),
    )
    await conn.commit()
    return {"materials_actual": mat, "labor_actual": lab, "equipment_actual": eq, "total_actual": total}


# ---------------------------------------------------------------------------
# Purchase requests
# ---------------------------------------------------------------------------

async def create_purchase_request(
    conn: aiosqlite.Connection,
    *,
    request_id: str,
    project_id: int,
    items: list,
    buyer_comment: str = "",
    proposal_filename: str = "",
    proposal_path: str = "",
    file_url: str = "",
    tg_message_id: Optional[int] = None,
    tg_chat_id: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO purchase_requests(
            id, project_id, status, items_json, buyer_comment,
            proposal_filename, proposal_path, file_url, tg_message_id, tg_chat_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            request_id, project_id, "pending",
            json.dumps(items, ensure_ascii=False),
            buyer_comment, proposal_filename, proposal_path, file_url,
            tg_message_id, tg_chat_id,
        ),
    )
    await conn.commit()


async def get_purchase_request(
    conn: aiosqlite.Connection, request_id: str
) -> Optional[Dict[str, Any]]:
    async with conn.execute(
        "SELECT * FROM purchase_requests WHERE id=?", (request_id,)
    ) as cur:
        row = await cur.fetchone()
        if not row:
            return None
        d = _row(row)
        try:
            d["items"] = json.loads(d.get("items_json") or "[]")
        except Exception:
            d["items"] = []
        return d


async def update_purchase_request(
    conn: aiosqlite.Connection,
    request_id: str,
    *,
    status: Optional[str] = None,
    resolved_at: Optional[str] = None,
    actor: Optional[str] = None,
    approver_comment: Optional[str] = None,
    tg_message_id: Optional[int] = None,
    tg_chat_id: Optional[str] = None,
) -> None:
    sets = []
    params: list = []
    if status is not None:
        sets.append("status=?"); params.append(status)
    if resolved_at is not None:
        sets.append("resolved_at=?"); params.append(resolved_at)
    if actor is not None:
        sets.append("actor=?"); params.append(actor)
    if approver_comment is not None:
        sets.append("approver_comment=?"); params.append(approver_comment)
    if tg_message_id is not None:
        sets.append("tg_message_id=?"); params.append(tg_message_id)
    if tg_chat_id is not None:
        sets.append("tg_chat_id=?"); params.append(tg_chat_id)
    if not sets:
        return
    params.append(request_id)
    await conn.execute(f"UPDATE purchase_requests SET {', '.join(sets)} WHERE id=?", params)
    await conn.commit()


async def get_pending_purchase_requests(
    conn: aiosqlite.Connection,
) -> List[Dict[str, Any]]:
    async with conn.execute(
        """
        SELECT pr.*, p.name AS project_name
        FROM purchase_requests pr
        JOIN projects p ON p.id = pr.project_id
        WHERE pr.status = 'pending'
        ORDER BY pr.created_at
        """,
    ) as cur:
        rows = await cur.fetchall()
    result = []
    for row in rows:
        d = _row(row)
        try:
            d["items"] = json.loads(d.get("items_json") or "[]")
        except Exception:
            d["items"] = []
        result.append(d)
    return result


async def get_all_purchase_requests(
    conn: aiosqlite.Connection,
    project_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if project_id:
        async with conn.execute(
            "SELECT * FROM purchase_requests WHERE project_id=? ORDER BY created_at DESC",
            (project_id,),
        ) as cur:
            rows = await cur.fetchall()
    else:
        async with conn.execute(
            "SELECT * FROM purchase_requests ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
    result = []
    for row in rows:
        d = _row(row)
        try:
            d["items"] = json.loads(d.get("items_json") or "[]")
        except Exception:
            d["items"] = []
        result.append(d)
    return result
