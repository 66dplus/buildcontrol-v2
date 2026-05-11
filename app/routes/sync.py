"""
POST /api/sync-from-bitrix — pull Bitrix24 workgroups + lists into local SQLite.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db.database import get_db
from app.services.sync_from_bitrix import sync_all_projects

router = APIRouter(prefix="", tags=["sync"])


@router.post("/api/sync-from-bitrix")
async def api_sync_from_bitrix() -> JSONResponse:
    """
    Walk every active Bitrix24 workgroup, find 5 BuildControl lists per workgroup,
    and write (or refresh) SQLite rows idempotently.

    Returns counts of synced objects and a list of skipped workgroup names.
    """
    async with get_db() as conn:
        result = await sync_all_projects(conn)
    return JSONResponse(content=result)
