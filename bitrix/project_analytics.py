"""
Read-only analytics queries for the director Telegram agent.

Each function fetches data from Bitrix24 Universal Lists and returns
clean Python dicts — no Bitrix internals leak to the caller.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from bitrix.client import BitrixClient
from bitrix.methods import lists, workgroups

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: Any) -> Optional[date]:
    """Parse Bitrix24 date string ('YYYY-MM-DD' or 'DD.MM.YYYY') to date."""
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _fmt_date(d: Optional[date]) -> Optional[str]:
    return d.strftime("%d.%m.%Y") if d else None


async def _list_context(
    client: BitrixClient,
    project_id: int,
    keyword: str,
) -> Optional[tuple[int, str, Dict[str, int], List[Dict[str, Any]]]]:
    """Return (list_id, iblock_code, field_map, elements) or None."""
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

async def list_projects(client: BitrixClient) -> List[Dict[str, Any]]:
    """
    Return all active projects.

    Result shape: [{"id": int, "name": str}]
    """
    return await workgroups.list_projects(client)


async def get_schedule_analysis(
    client: BitrixClient,
    project_id: int,
) -> Dict[str, Any]:
    """
    Analyse task schedule for a project against today's date.

    Returns a dict with:
      - tasks: list of task dicts
      - summary: counts and budget totals per category
      - today: current date string

    Each task dict:
      etap, zadacha, date_start_plan, date_end_plan,
      date_start_fact, date_end_fact, completion_pct,
      budget_fact, status_label
    """
    today = date.today()

    ctx = await _list_context(client, project_id, "задач")
    if not ctx:
        return {"error": f"Список 'Этапы и задачи' не найден для проекта {project_id}"}
    _, _, fm, elements = ctx

    tasks: List[Dict[str, Any]] = []
    for elem in elements:
        etap = lists.get_prop_value_str(elem, fm.get(_find_key(fm, "этап"), -1)) if _find_key(fm, "этап") else None
        zadacha = elem.get("NAME", "")

        pid_start_plan = _find_pid(fm, "дата нач. план")
        pid_end_plan   = _find_pid(fm, "дата ок. план")
        pid_start_fact = _find_pid(fm, "дата нач. факт")
        pid_end_fact   = _find_pid(fm, "дата ок. факт")
        pid_completion = _find_pid(fm, "готовн. факт")
        pid_budget_fact = _find_pid(fm, "бюджет факт")

        date_start_plan = _parse_date(lists.get_prop_value_str(elem, pid_start_plan)) if pid_start_plan else None
        date_end_plan   = _parse_date(lists.get_prop_value_str(elem, pid_end_plan))   if pid_end_plan   else None
        date_start_fact = _parse_date(lists.get_prop_value_str(elem, pid_start_fact)) if pid_start_fact else None
        date_end_fact   = _parse_date(lists.get_prop_value_str(elem, pid_end_fact))   if pid_end_fact   else None
        completion_pct  = lists.get_prop_value(elem, pid_completion)                  if pid_completion  else None
        budget_fact     = lists.get_prop_value(elem, pid_budget_fact)                 if pid_budget_fact else None

        pct = completion_pct or 0.0

        # Classify status
        if date_end_fact or pct >= 100:
            status = "done"
            label = "Завершена"
        elif date_end_plan and date_end_plan < today and pct < 100:
            status = "overdue"
            label = f"Просрочена ({pct:.0f}%)"
        elif date_start_fact or 0 < pct < 100:
            status = "in_progress"
            label = f"В работе ({pct:.0f}%)"
        elif date_start_plan and date_start_plan <= today:
            status = "should_start"
            label = "Должна быть начата"
        else:
            status = "not_started"
            label = "Не начата"

        tasks.append({
            "etap": etap or "",
            "zadacha": zadacha,
            "date_start_plan": _fmt_date(date_start_plan),
            "date_end_plan": _fmt_date(date_end_plan),
            "date_start_fact": _fmt_date(date_start_fact),
            "date_end_fact": _fmt_date(date_end_fact),
            "completion_pct": pct,
            "budget_fact": budget_fact or 0.0,
            "status": status,
            "status_label": label,
        })

    # Summaries
    overdue    = [t for t in tasks if t["status"] == "overdue"]
    done       = [t for t in tasks if t["status"] == "done"]
    in_progress = [t for t in tasks if t["status"] == "in_progress"]
    not_started = [t for t in tasks if t["status"] == "not_started"]
    should_start = [t for t in tasks if t["status"] == "should_start"]

    summary = {
        "total": len(tasks),
        "done": len(done),
        "in_progress": len(in_progress),
        "overdue": len(overdue),
        "not_started": len(not_started),
        "should_start": len(should_start),
        "budget_fact_overdue": round(sum(t["budget_fact"] for t in overdue), 2),
        "budget_fact_done": round(sum(t["budget_fact"] for t in done), 2),
        "budget_fact_total": round(sum(t["budget_fact"] for t in tasks), 2),
    }

    return {
        "today": today.strftime("%d.%m.%Y"),
        "summary": summary,
        "tasks": tasks,
    }


async def get_budget_overview(
    client: BitrixClient,
    project_id: int,
) -> Dict[str, Any]:
    """
    Return per-phase budget: plan vs actual broken down by category.

    Result shape:
      {
        phases: [{
          phase, materials_plan, labor_plan, equipment_plan, total_plan,
          materials_fact, labor_fact, equipment_fact, total_fact,
          deviation_pct
        }],
        totals: { same keys summed across phases }
      }
    """
    ctx = await _list_context(client, project_id, "бюджет")
    if not ctx:
        return {"error": f"Список 'Бюджет' не найден для проекта {project_id}"}
    _, _, fm, elements = ctx

    phases = []
    for elem in elements:
        phase_name = elem.get("NAME", "")

        mat_plan  = lists.sum_prop_values([elem], fm, "материалы план")
        lab_plan  = lists.sum_prop_values([elem], fm, "фот план")
        eq_plan   = lists.sum_prop_values([elem], fm, "техника план")
        total_plan = lists.sum_prop_values([elem], fm, "итого план")
        if total_plan == 0:
            total_plan = mat_plan + lab_plan + eq_plan

        mat_fact  = lists.sum_prop_values([elem], fm, "материалы факт")
        lab_fact  = lists.sum_prop_values([elem], fm, "фот факт")
        eq_fact   = lists.sum_prop_values([elem], fm, "техника факт")
        total_fact = lists.sum_prop_values([elem], fm, "итого факт")
        if total_fact == 0:
            total_fact = mat_fact + lab_fact + eq_fact

        deviation_pct = round(
            ((total_fact - total_plan) / total_plan * 100) if total_plan else 0.0, 1
        )

        phases.append({
            "phase": phase_name,
            "materials_plan": round(mat_plan, 2),
            "labor_plan": round(lab_plan, 2),
            "equipment_plan": round(eq_plan, 2),
            "total_plan": round(total_plan, 2),
            "materials_fact": round(mat_fact, 2),
            "labor_fact": round(lab_fact, 2),
            "equipment_fact": round(eq_fact, 2),
            "total_fact": round(total_fact, 2),
            "deviation_pct": deviation_pct,
        })

    totals: Dict[str, float] = {
        "materials_plan": round(sum(p["materials_plan"] for p in phases), 2),
        "labor_plan":     round(sum(p["labor_plan"]     for p in phases), 2),
        "equipment_plan": round(sum(p["equipment_plan"] for p in phases), 2),
        "total_plan":     round(sum(p["total_plan"]     for p in phases), 2),
        "materials_fact": round(sum(p["materials_fact"] for p in phases), 2),
        "labor_fact":     round(sum(p["labor_fact"]     for p in phases), 2),
        "equipment_fact": round(sum(p["equipment_fact"] for p in phases), 2),
        "total_fact":     round(sum(p["total_fact"]     for p in phases), 2),
    }
    if totals["total_plan"]:
        totals["deviation_pct"] = round(
            (totals["total_fact"] - totals["total_plan"]) / totals["total_plan"] * 100, 1
        )
    else:
        totals["deviation_pct"] = 0.0

    return {"phases": phases, "totals": totals}


async def get_resource_costs(
    client: BitrixClient,
    project_id: int,
    etap: Optional[str] = None,
    zadacha: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Return granular material/labor/equipment rows for a project,
    optionally filtered by phase (etap) and/or task (zadacha).

    Result shape:
      {
        materials: [{name, qty_plan, qty_fact, cost_plan, cost_fact}],
        labor:     [{specialty, hours_plan, hours_fact, payroll_plan, payroll_fact}],
        equipment: [{name, hours_plan, hours_fact, cost_plan, cost_fact}],
        totals:    {cost_plan, cost_fact, deviation_pct}
      }
    """
    filters: Dict[str, str] = {}
    if etap:
        filters["Этап"] = etap
    if zadacha:
        filters["Задача"] = zadacha

    # ---- Materials ----
    materials: List[Dict[str, Any]] = []
    mat_ctx = await _list_context(client, project_id, "материал")
    if mat_ctx:
        _, _, fm, elems = mat_ctx
        rows = lists.find_elements_by_properties(elems, fm, filters) if filters else elems
        for r in rows:
            materials.append({
                "name":      r.get("NAME", ""),
                "qty_plan":  lists.get_prop_value(r, _find_pid(fm, "объём план") or -1),
                "qty_fact":  lists.get_prop_value(r, _find_pid(fm, "объём израсход") or -1),
                "cost_plan": lists.get_prop_value(r, _find_pid(fm, "стоим. план") or -1),
                "cost_fact": lists.get_prop_value(r, _find_pid(fm, "стоим. факт") or -1),
            })

    # ---- Labor ----
    labor: List[Dict[str, Any]] = []
    lab_ctx = await _list_context(client, project_id, "трудозатрат")
    if lab_ctx:
        _, _, fm, elems = lab_ctx
        rows = lists.find_elements_by_properties(elems, fm, filters) if filters else elems
        for r in rows:
            labor.append({
                "specialty":    r.get("NAME", ""),
                "hours_plan":   lists.get_prop_value(r, _find_pid(fm, "ч-часов план") or -1),
                "hours_fact":   lists.get_prop_value(r, _find_pid(fm, "ч-часов факт") or -1),
                "payroll_plan": lists.get_prop_value(r, _find_pid(fm, "фот план") or -1),
                "payroll_fact": lists.get_prop_value(r, _find_pid(fm, "фот факт") or -1),
            })

    # ---- Equipment ----
    equipment: List[Dict[str, Any]] = []
    eq_ctx = await _list_context(client, project_id, "техник")
    if eq_ctx:
        _, _, fm, elems = eq_ctx
        rows = lists.find_elements_by_properties(elems, fm, filters) if filters else elems
        for r in rows:
            equipment.append({
                "name":       r.get("NAME", ""),
                "hours_plan": lists.get_prop_value(r, _find_pid(fm, "часов план") or -1),
                "hours_fact": lists.get_prop_value(r, _find_pid(fm, "часов факт") or -1),
                "cost_plan":  lists.get_prop_value(r, _find_pid(fm, "итого план") or -1),
                "cost_fact":  lists.get_prop_value(r, _find_pid(fm, "итого факт") or -1),
            })

    total_cost_plan = (
        sum(r["cost_plan"] or 0 for r in materials)
        + sum(r["payroll_plan"] or 0 for r in labor)
        + sum(r["cost_plan"] or 0 for r in equipment)
    )
    total_cost_fact = (
        sum(r["cost_fact"] or 0 for r in materials)
        + sum(r["payroll_fact"] or 0 for r in labor)
        + sum(r["cost_fact"] or 0 for r in equipment)
    )
    deviation_pct = (
        round((total_cost_fact - total_cost_plan) / total_cost_plan * 100, 1)
        if total_cost_plan else 0.0
    )

    return {
        "materials": materials,
        "labor": labor,
        "equipment": equipment,
        "totals": {
            "cost_plan": round(total_cost_plan, 2),
            "cost_fact": round(total_cost_fact, 2),
            "deviation_pct": deviation_pct,
        },
    }


async def get_upcoming_tasks(
    client: BitrixClient,
    project_id: int,
    days: int = 7,
) -> Dict[str, Any]:
    """
    Return tasks starting or ending within the next `days` days.

    Result shape:
      {
        "window_days": int,
        "starting": [task dicts],
        "ending":   [task dicts]
      }
    """
    today = date.today()

    ctx = await _list_context(client, project_id, "задач")
    if not ctx:
        return {"error": f"Список 'Этапы и задачи' не найден для проекта {project_id}"}
    _, _, fm, elements = ctx

    pid_start_plan = _find_pid(fm, "дата нач. план")
    pid_end_plan   = _find_pid(fm, "дата ок. план")
    pid_completion = _find_pid(fm, "готовн. факт")

    starting: List[Dict[str, Any]] = []
    ending: List[Dict[str, Any]] = []

    for elem in elements:
        zadacha = elem.get("NAME", "")
        etap_pid = _find_pid(fm, "этап")
        etap = lists.get_prop_value_str(elem, etap_pid) if etap_pid else ""

        date_start = _parse_date(lists.get_prop_value_str(elem, pid_start_plan)) if pid_start_plan else None
        date_end   = _parse_date(lists.get_prop_value_str(elem, pid_end_plan))   if pid_end_plan   else None
        pct        = lists.get_prop_value(elem, pid_completion)                   if pid_completion  else 0.0

        base = {
            "etap": etap or "",
            "zadacha": zadacha,
            "completion_pct": pct or 0.0,
            "date_start_plan": _fmt_date(date_start),
            "date_end_plan":   _fmt_date(date_end),
        }

        if date_start and today <= date_start <= _offset(today, days):
            starting.append(base)
        if date_end and today <= date_end <= _offset(today, days) and (pct or 0) < 100:
            ending.append(base)

    return {"window_days": days, "starting": starting, "ending": ending}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_key(field_map: Dict[str, int], keyword: str) -> Optional[str]:
    """Return the first field name that contains keyword (case-insensitive)."""
    kw = keyword.lower()
    for fname in field_map:
        if kw in fname.lower():
            return fname
    return None


def _find_pid(field_map: Dict[str, int], keyword: str) -> Optional[int]:
    """Return property ID for the first field matching keyword."""
    key = _find_key(field_map, keyword)
    return field_map[key] if key else None


def _offset(d: date, days: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=days)
