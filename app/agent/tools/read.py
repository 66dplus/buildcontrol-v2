"""Read-only agent tools: list_projects, query_database."""
from __future__ import annotations

import logging
from typing import Any

from app.agent.tools import _register
from db.database import get_db

logger = logging.getLogger(__name__)


@_register({
    "type": "function",
    "function": {
        "name": "list_projects",
        "description": "Return all active construction projects with their IDs and names.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "write": False,
})
async def _list_projects(**_: Any) -> Any:
    async with get_db() as conn:
        async with conn.execute(
            "SELECT id, name FROM projects WHERE is_archived=0 ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
            return [{"id": r[0], "name": r[1]} for r in rows]


@_register({
    "type": "function",
    "function": {
        "name": "query_database",
        "description": "Execute a SELECT query against the local SQLite database.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Valid SQLite SELECT query"}
            },
            "required": ["sql"],
        },
    },
    "write": False,
})
async def _query_database(sql: str, **_: Any) -> Any:
    sql_clean = sql.strip().rstrip(";")
    if not sql_clean.upper().lstrip().startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed"}
    if "LIMIT" not in sql_clean.upper():
        sql_clean += " LIMIT 200"
    try:
        async with get_db() as conn:
            async with conn.execute(sql_clean) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("query_database sql=%r: %s", sql_clean, exc)
        return {"error": str(exc)}
