"""Audit log writer for agent tool calls."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

from db.database import get_db

logger = logging.getLogger(__name__)


async def write_audit_log_conn(
    conn: aiosqlite.Connection,
    *,
    session_id: Optional[str],
    tool_name: str,
    args: Any,
    result: Any,
    error: Optional[str],
) -> None:
    """Write one audit row to an already-open connection."""
    ts = datetime.now(timezone.utc).isoformat()
    args_json = json.dumps(args, ensure_ascii=False, default=str)
    result_json = (
        json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
    )
    await conn.execute(
        """INSERT INTO audit_log
           (timestamp, session_id, tool_name, args_json, result_json, error)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ts, session_id, tool_name, args_json, result_json, error),
    )
    await conn.commit()


async def write_audit_log(
    *,
    session_id: Optional[str],
    tool_name: str,
    args: Any,
    result: Any,
    error: Optional[str],
) -> None:
    """Write one audit row via get_db(). Silently swallows failures."""
    try:
        async with get_db() as conn:
            await write_audit_log_conn(
                conn,
                session_id=session_id,
                tool_name=tool_name,
                args=args,
                result=result,
                error=error,
            )
    except Exception as exc:
        logger.warning("audit_log write failed: %s", exc)
