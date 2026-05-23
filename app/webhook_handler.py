"""
FastAPI application entry point for BuildControl.

Registers all domain routers and keeps only the shared/utility endpoints:
  GET  /health           — health check
  POST /api/test-digest  — manually trigger morning digest
  GET  /api/projects/{id}/members — workgroup members (Bitrix call)
  POST /api/agent/assign-preview  — NL assignment parsing via LLM
  POST /api/agent/apply-assignments — apply phase assignments to Bitrix tasks
  (SPA catch-all and static-file mounts)

Domain routes live in app/routes/:
  dashboard.py — /api/dashboard/summary, /api/whoami, /api/projects/{id}/phases
  projects.py  — /api/projects and /api/projects/{id}/* data endpoints
  reports.py   — /api/report, /api/purchase-request, /api/buyer-report
  imports.py   — POST /upload, GET /api/import-status/{job_id}
  agent.py     — POST /api/agent/chat, POST /api/agent/confirm
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bitrix.client import BitrixClient
from config import settings
from db.database import get_db

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown: init SQLite DB, manage APScheduler for daily digest."""
    from db.database import init_db
    from app.notifications.digest import send_morning_digest

    await init_db()

    scheduler = AsyncIOScheduler()
    if settings.notifications_enabled:
        from app.notifications.digest import send_weekly_digest
        scheduler.add_job(
            send_morning_digest,
            "cron",
            hour=9,
            minute=0,
            timezone="Europe/Moscow",
            id="morning_digest",
        )
        scheduler.add_job(
            send_weekly_digest,
            "cron",
            day_of_week="mon",
            hour=9,
            minute=0,
            timezone="Europe/Moscow",
            id="weekly_digest",
        )
        scheduler.start()
        logger.info("Notification scheduler started — morning digest at 09:00 MSK, weekly digest on Mondays")
    else:
        logger.info("Notifications disabled — scheduler not started")

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Notification scheduler stopped")


app = FastAPI(
    title="BuildControl Upload API",
    description="Upload Excel file → auto-create Bitrix24 project + lists + tasks",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow Bitrix24 iframe to call /upload cross-origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

from app.bitrix_app import router as bitrix_router  # noqa: E402
from app.approval_page import router as approval_router  # noqa: E402
from app.telegram_bot import router as telegram_router  # noqa: E402
from app.routes.dashboard import router as dashboard_router  # noqa: E402
from app.routes.projects import router as projects_router  # noqa: E402
from app.routes.reports import router as reports_router  # noqa: E402
from app.routes.imports import router as imports_router  # noqa: E402
from app.routes.agent import router as agent_router  # noqa: E402
from app.routes.sync import router as sync_router  # noqa: E402
app.include_router(bitrix_router)
app.include_router(approval_router)
app.include_router(telegram_router)
app.include_router(dashboard_router)
app.include_router(projects_router)
app.include_router(reports_router)
app.include_router(imports_router)
app.include_router(agent_router)
app.include_router(sync_router)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "service": "BuildControl Upload API"}


@app.post("/api/test-digest")
async def test_digest() -> JSONResponse:
    """Manually trigger the morning digest (for testing)."""
    from app.notifications.digest import send_morning_digest
    await send_morning_digest()
    return JSONResponse(content={"status": "digest_sent"})


@app.get("/api/projects/{project_id}/members")
async def api_project_members(project_id: int) -> JSONResponse:
    """
    Return Bitrix24 workgroup members for the given project.

    project_id == Bitrix workgroup ID (projects.id is the workgroup ID).
    Returns [{id, name, last_name}].
    """
    async with get_db() as conn:
        async with conn.execute(
            "SELECT id FROM projects WHERE id=?", (project_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    async with BitrixClient() as client:
        resp = await client.call("sonet_group.user.get", {"ID": project_id})
    users_raw = resp.get("result", []) if isinstance(resp.get("result"), list) else []

    members = [
        {
            "id": int(u.get("USER_ID", 0)),
            "name": u.get("USER_NAME", ""),
            "last_name": u.get("USER_LAST_NAME", ""),
        }
        for u in users_raw
        if u.get("USER_ID")
    ]
    return JSONResponse(content=members)


@app.post("/api/agent/assign-preview")
async def api_assign_preview(request: Request) -> JSONResponse:
    """
    Parse a natural-language assignment string into a structured table.

    Body:
      {
        "project_id": 1,
        "text": "Алексея на этапы 1-3, Андрея на Каркас",
        "users": [{"id": 5, "name": "Алексей", "last_name": "Петров"}, ...],
        "phases": ["Этап 1", "Этап 2", ...]
      }

    Returns:
      {"assignments": [{"phase": "Этап 1", "responsible_id": 5, "responsible_name": "Алексей Петров"}, ...]}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    text = (body.get("text") or "").strip()
    users = body.get("users") or []
    phases = body.get("phases") or []

    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if not settings.openrouter_api_key:
        # Demo fallback — assign everyone to user 1
        return JSONResponse(content={"assignments": [
            {"phase": p, "responsible_id": 1, "responsible_name": "Demo user"}
            for p in phases
        ]})

    from openai import AsyncOpenAI
    import json as _json

    client_llm = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    users_str = "\n".join(
        f"  ID {u['id']}: {u.get('name', '')} {u.get('last_name', '')}".strip()
        for u in users
    ) or "  (no data)"
    phases_str = "\n".join(f"  - {p}" for p in phases) or "  (no data)"

    prompt = (
        "Match each phase with a responsible person from the text.\n"
        f"Users:\n{users_str}\n\nPhases:\n{phases_str}\n\nText: \"{text}\"\n\n"
        "Reply ONLY with valid JSON:\n"
        "{\"assignments\": [{\"phase\": \"...\", \"responsible_id\": N, \"responsible_name\": \"...\"}]}"
    )

    try:
        resp = await client_llm.chat.completions.create(
            model=settings.openrouter_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = _json.loads(raw)
        return JSONResponse(content=parsed)
    except Exception as exc:
        logger.exception("assign-preview LLM call failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"LLM error: {exc}")


@app.post("/api/agent/apply-assignments")
async def api_apply_assignments(request: Request) -> JSONResponse:
    """
    Apply phase-responsible_id assignments to existing Bitrix24 tasks + SQLite.

    Body:
      {
        "project_id": 1,
        "assignments": [
          {"phase": "Phase 1", "responsible_id": 5},
          ...
        ]
      }

    Updates tasks.task.update in Bitrix24 for each task in the phase,
    and writes an audit log row per assignment.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    project_id = body.get("project_id")
    assignments = body.get("assignments") or []

    if not project_id or not assignments:
        raise HTTPException(status_code=400, detail="project_id and assignments required")

    # Build a {phase -> responsible_id} map.
    phase_map: dict[str, int] = {}
    for a in assignments:
        phase = (a.get("phase") or "").strip()
        resp_id = a.get("responsible_id")
        if phase and resp_id:
            phase_map[phase] = int(resp_id)

    if not phase_map:
        return JSONResponse(content={"updated": 0})

    # Load tasks from SQLite.
    async with get_db() as conn:
        async with conn.execute(
            "SELECT id, bitrix_task_id, phase FROM tasks WHERE project_id=?",
            (project_id,),
        ) as cur:
            task_rows = await cur.fetchall()

    updated = 0
    errors: list[str] = []

    async with BitrixClient() as bx:
        for row in task_rows:
            phase = (row["phase"] or "").strip()
            responsible_id = phase_map.get(phase)
            if not responsible_id:
                continue
            bx_task_id = row["bitrix_task_id"]
            if bx_task_id:
                try:
                    await bx.call("tasks.task.update", {
                        "taskId": int(bx_task_id),
                        "fields": {"RESPONSIBLE_ID": responsible_id},
                    })
                except Exception as exc:
                    errors.append(f"task {bx_task_id}: {exc}")
                    continue
            updated += 1

    # Audit log
    from app.agent_tools import _write_audit_log
    await _write_audit_log(
        "apply_assignments",
        {"project_id": project_id, "phase_map": phase_map},
        {"updated": updated, "errors": errors},
        "confirmed",
    )

    return JSONResponse(content={"updated": updated, "errors": errors})


# ---------------------------------------------------------------------------
# React SPA support — must be registered AFTER all /api/* routes so the
# catch-all does not shadow them.
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
_SPA_ROUTES: tuple[str, ...] = (
    "/", "/projects", "/ai", "/foreman-report", "/procurement", "/upload",
)


def _spa_index_response() -> Union[FileResponse, JSONResponse]:
    index = _FRONTEND_DIST / "index.html"
    if not index.is_file():
        return JSONResponse(
            {"detail": "Frontend not built. Run `npm --prefix frontend run build`."},
            status_code=503,
        )
    return FileResponse(index, media_type="text/html")


if _FRONTEND_DIST.is_dir():
    # Serve static assets at /assets/* (Vite output folder).
    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="spa-assets")

    @app.get("/favicon.svg", include_in_schema=False, response_model=None)
    async def spa_favicon():
        f = _FRONTEND_DIST / "favicon.svg"
        if f.is_file():
            return FileResponse(f, media_type="image/svg+xml")
        return JSONResponse({"detail": "not found"}, status_code=404)


@app.get("/", include_in_schema=False, response_model=None)
async def spa_root():
    return _spa_index_response()


@app.get("/{spa_path:path}", include_in_schema=False, response_model=None)
async def spa_catchall(spa_path: str):
    """
    Catch-all for client-side routes (React Router). Excludes API/webhook paths
    so they keep their normal 404 behavior when hit with a wrong method/typo.
    """
    if spa_path.startswith(("api/", "bitrix/", "approval/", "upload",
                            "health", "telegram", "assets/")):
        raise HTTPException(status_code=404, detail="Not Found")
    return _spa_index_response()
