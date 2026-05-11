from collections import defaultdict
from datetime import date as _date
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from db.database import get_db
from db import repo

router = APIRouter(prefix="", tags=["dashboard"])


@router.get("/api/projects/{project_id}/phases")
async def api_phases(project_id: int) -> JSONResponse:
    """
    Return budget_phases rows for a project — read directly from SQLite.

    Used by the SPA Dashboard (PortfolioChart) and Project Detail (PhaseChart)
    to show plan vs actual per phase. No Bitrix calls.
    """
    async with get_db() as conn:
        phases = await repo.get_budget_phases(conn, project_id)
    return JSONResponse(content=phases)


@router.get("/api/dashboard/summary")
async def api_dashboard_summary() -> JSONResponse:
    """
    Aggregate snapshot for the Dashboard landing page.

    Returns one entry per active project with totals summed from budget_phases:
      { id, name, total_plan, total_actual, materials_plan/actual,
        labor_plan/actual, equipment_plan/actual, variance_pct }

    Plus portfolio-level KPIs:
      { total_plan, total_actual, anomaly_count }
    where anomaly_count = projects with variance_pct > 15.
    """
    async with get_db() as conn:
        projects = await repo.get_projects(conn)
        today_str = _date.today().isoformat()
        # Pre-compute the set of project ids that are behind schedule.
        behind_q = await conn.execute(
            "SELECT DISTINCT project_id FROM tasks "
            "WHERE date_end_plan IS NOT NULL AND date_end_plan < ? AND completion_pct < 100",
            (today_str,),
        )
        behind_ids = {int(r[0]) for r in await behind_q.fetchall()}
        behind_count = len(behind_ids)
        rows: list[dict[str, Any]] = []
        portfolio_plan = 0.0
        portfolio_actual = 0.0
        anomaly_count = 0
        for p in projects:
            phases = await repo.get_budget_phases(conn, p["id"])
            mat_plan = sum(ph["materials_plan"] or 0 for ph in phases)
            lab_plan = sum(ph["labor_plan"] or 0 for ph in phases)
            eq_plan = sum(ph["equipment_plan"] or 0 for ph in phases)
            mat_actual = sum(ph["materials_actual"] or 0 for ph in phases)
            lab_actual = sum(ph["labor_actual"] or 0 for ph in phases)
            eq_actual = sum(ph["equipment_actual"] or 0 for ph in phases)
            total_plan = sum(ph["total_plan"] or 0 for ph in phases)
            total_actual = sum(ph["total_actual"] or 0 for ph in phases)
            variance_pct = (
                ((total_actual - total_plan) / total_plan) * 100.0
                if total_plan
                else 0.0
            )

            # Schedule-aware: expected cumulative plan spend as of today.
            async with conn.execute(
                "SELECT date_start_plan, budget_plan FROM tasks "
                "WHERE project_id=? AND date_start_plan IS NOT NULL AND date_start_plan != '' "
                "AND date_start_plan <= ?",
                (p["id"], today_str),
            ) as cur:
                expected_rows = await cur.fetchall()
            expected_by_today = sum(float(r[1] or 0) for r in expected_rows)
            schedule_variance_abs = total_actual - expected_by_today
            schedule_variance_pct = (
                (schedule_variance_abs / expected_by_today) * 100.0
                if expected_by_today > 0
                else 0.0
            )

            if variance_pct > 15:
                anomaly_count += 1
            portfolio_plan += total_plan
            portfolio_actual += total_actual
            rows.append({
                "id": p["id"],
                "name": p["name"],
                "materials_plan": mat_plan,
                "materials_actual": mat_actual,
                "labor_plan": lab_plan,
                "labor_actual": lab_actual,
                "equipment_plan": eq_plan,
                "equipment_actual": eq_actual,
                "total_plan": total_plan,
                "total_actual": total_actual,
                "variance_pct": variance_pct,
                "phase_count": len(phases),
                "is_behind": p["id"] in behind_ids,
                "expected_by_today": expected_by_today,
                "schedule_variance_abs": schedule_variance_abs,
                "schedule_variance_pct": schedule_variance_pct,
            })
    return JSONResponse({
        "projects": rows,
        "kpi": {
            "total_plan": portfolio_plan,
            "total_actual": portfolio_actual,
            "anomaly_count": anomaly_count,
            "behind_count": behind_count,
        },
    })


@router.get("/api/projects/{project_id}/budget-timeline")
async def api_budget_timeline(project_id: int) -> JSONResponse:
    """
    Plan vs Actual time series for the project budget chart.

    plan_series  — cumulative planned spend, one point per task start date
                   (step function: plan jumps by budget_plan when a task begins)
    actual_series — running actual totals recorded after each foreman report,
                   one point per snapshot date
    """
    async with get_db() as conn:
        # Plan series: derived from task dates (budget_plan accumulates as tasks start)
        async with conn.execute(
            "SELECT date_start_plan, budget_plan FROM tasks "
            "WHERE project_id=? AND date_start_plan IS NOT NULL AND date_start_plan != '' "
            "ORDER BY date_start_plan",
            (project_id,),
        ) as cur:
            task_rows = await cur.fetchall()

        plan_by_date: dict[str, float] = defaultdict(float)
        for row in task_rows:
            plan_by_date[row[0]] += float(row[1] or 0)

        plan_series: list[dict[str, Any]] = []
        running_plan = 0.0
        for date_str in sorted(plan_by_date):
            plan_series.append({"date": date_str, "total": running_plan})
            running_plan += plan_by_date[date_str]
        if plan_series:
            # Close the line at the last step value
            plan_series.append({"date": plan_series[-1]["date"], "total": running_plan})
        elif task_rows:
            plan_series.append({"date": task_rows[0][0], "total": 0})

        # Actual series: from budget_snapshots (running totals per report day)
        async with conn.execute(
            "SELECT snapshot_date, mat_actual, lab_actual, eq_actual, total_actual "
            "FROM budget_snapshots WHERE project_id=? ORDER BY snapshot_date",
            (project_id,),
        ) as cur:
            snap_rows = await cur.fetchall()

        actual_series = [
            {
                "date": r[0],
                "total": float(r[4] or 0),
                "materials": float(r[1] or 0),
                "labor": float(r[2] or 0),
                "equipment": float(r[3] or 0),
            }
            for r in snap_rows
        ]

        # Anomaly annotation: compare each actual point to plan at same date
        plan_map = {p["date"]: p["total"] for p in plan_series}
        plan_dates_sorted = sorted(plan_map)

        def _plan_at(date_str: str) -> float:
            """Interpolate plan value at a given date."""
            if not plan_dates_sorted:
                return 0.0
            prev = 0.0
            for pd in plan_dates_sorted:
                if pd <= date_str:
                    prev = plan_map[pd]
                else:
                    break
            return prev

        for point in actual_series:
            plan_val = _plan_at(point["date"])
            if plan_val > 0:
                variance_pct = (point["total"] - plan_val) / plan_val * 100
                point["variance_pct"] = round(variance_pct, 1)
                if variance_pct > 10:
                    point["anomaly"] = "red"
                elif variance_pct > 0:
                    point["anomaly"] = "yellow"
                else:
                    point["anomaly"] = "green"
            else:
                point["variance_pct"] = 0.0
                point["anomaly"] = None

    return JSONResponse({"plan_series": plan_series, "actual_series": actual_series})


@router.get("/api/dashboard/budget-timeline")
async def api_dashboard_budget_timeline() -> JSONResponse:
    """
    Aggregated Plan vs Actual over time for all active projects combined.
    Same shape as the per-project endpoint.
    """
    async with get_db() as conn:
        projects = await repo.get_projects(conn)
        project_ids = [p["id"] for p in projects]

        plan_by_date: dict[str, float] = defaultdict(float)
        for pid in project_ids:
            async with conn.execute(
                "SELECT date_start_plan, budget_plan FROM tasks "
                "WHERE project_id=? AND date_start_plan IS NOT NULL AND date_start_plan != '' "
                "ORDER BY date_start_plan",
                (pid,),
            ) as cur:
                for row in await cur.fetchall():
                    plan_by_date[row[0]] += float(row[1] or 0)

        plan_series: list[dict[str, Any]] = []
        running_plan = 0.0
        for date_str in sorted(plan_by_date):
            plan_series.append({"date": date_str, "total": running_plan})
            running_plan += plan_by_date[date_str]
        if plan_series:
            plan_series.append({"date": plan_series[-1]["date"], "total": running_plan})

        async with conn.execute(
            "SELECT snapshot_date, "
            "  SUM(mat_actual), SUM(lab_actual), SUM(eq_actual), SUM(total_actual) "
            "FROM budget_snapshots "
            "WHERE project_id IN ({}) "
            "GROUP BY snapshot_date ORDER BY snapshot_date".format(
                ",".join("?" * len(project_ids))
            ),
            tuple(project_ids),
        ) as cur:
            snap_rows = await cur.fetchall()

        actual_series = [
            {
                "date": r[0],
                "total": float(r[4] or 0),
                "materials": float(r[1] or 0),
                "labor": float(r[2] or 0),
                "equipment": float(r[3] or 0),
                "variance_pct": 0.0,
                "anomaly": None,
            }
            for r in snap_rows
        ]

    return JSONResponse({"plan_series": plan_series, "actual_series": actual_series})


@router.get("/api/whoami")
async def api_whoami(request: Request) -> JSONResponse:
    """
    Identify the calling client. Used by the React SPA on mount to decide
    auth flow and capabilities.

    Detection:
      - host="bitrix" if request carries a BX24 placement hint (header or query
        param ``bx24_domain``); the SPA then expects to live in an iframe.
      - host="standalone" otherwise.

    The role/user fields are placeholders for the MVP — full role-based auth
    is a separate workstream. The SPA only uses ``host`` to gate redirects.
    """
    bx_domain = (
        request.query_params.get("bx24_domain")
        or request.headers.get("x-bx24-domain")
        or ""
    ).strip()
    host = "bitrix" if bx_domain else "standalone"
    return JSONResponse({
        "user": "director",
        "role": "director",
        "host": host,
        "capabilities": ["chat", "voice", "upload", "reports"],
    })
