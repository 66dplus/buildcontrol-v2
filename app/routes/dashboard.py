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
            })
    return JSONResponse({
        "projects": rows,
        "kpi": {
            "total_plan": portfolio_plan,
            "total_actual": portfolio_actual,
            "anomaly_count": anomaly_count,
        },
    })


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
