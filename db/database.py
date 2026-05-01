"""
Async SQLite connection management for BuildControl.

init_db() must be called once at startup (the lifespan handler in webhook_handler.py).
get_db() is an async context manager that yields a ready connection.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite

from config import settings

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def init_db() -> None:
    """Create tables from schema.sql if they don't exist yet, then run migrations."""
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(settings.db_path) as conn:
        await conn.executescript(schema)
        await conn.commit()
        await _run_migrations(conn)
    logger.info("SQLite DB initialised at %s", settings.db_path)


async def _run_migrations(conn: aiosqlite.Connection) -> None:
    """Idempotent schema migrations for existing databases."""
    try:
        await conn.execute(
            "ALTER TABLE purchase_requests ADD COLUMN file_url TEXT DEFAULT ''"
        )
        await conn.commit()
        logger.info("Migration: added purchase_requests.file_url")
    except Exception:
        pass  # column already exists

    await _dedupe_and_index(conn)


# Dedupe spec: (table, key columns, sum columns, max columns)
_DEDUPE_TABLES = (
    (
        "materials",
        ("project_id", "phase", "task_name", "material_name"),
        ("qty_bought", "qty_consumed", "qty_stock", "cost_actual"),
        ("unit", "price_plan", "qty_plan", "cost_plan", "price_actual", "bitrix_element_id"),
    ),
    (
        "labor",
        ("project_id", "phase", "task_name", "specialty"),
        ("hours_actual", "payroll_actual"),
        ("rate", "hours_plan", "payroll_plan", "bitrix_element_id"),
    ),
    (
        "equipment_items",
        ("project_id", "phase", "task_name", "equipment_name"),
        ("hours_actual", "total_actual"),
        ("price_per_hour", "hours_plan", "total_plan", "bitrix_element_id"),
    ),
)

_INDEX_NAMES = {
    "materials": "uq_materials_proj_phase_task_name",
    "labor": "uq_labor_proj_phase_task_specialty",
    "equipment_items": "uq_equipment_proj_phase_task_name",
}


async def _dedupe_and_index(conn: aiosqlite.Connection) -> None:
    """Collapse duplicate rows in materials/labor/equipment_items, then add unique indexes.

    Aggregates accumulated fact columns (SUM) into the row with MAX(id) and deletes
    older duplicates. Idempotent — on a clean DB the dedupe loop finds nothing.
    """
    for table, key_cols, sum_cols, max_cols in _DEDUPE_TABLES:
        try:
            key_list = ", ".join(key_cols)
            async with conn.execute(
                f"SELECT {key_list}, COUNT(*) FROM {table} GROUP BY {key_list} HAVING COUNT(*) > 1"
            ) as cur:
                groups = await cur.fetchall()
        except Exception as e:
            logger.warning("Migration: dedupe scan failed for %s: %s", table, e)
            continue

        for grp in groups:
            key_vals = tuple(grp[: len(key_cols)])
            where_clause = " AND ".join(f"{c}=?" for c in key_cols)

            # Aggregate fact + plan columns from all duplicates. Order matters:
            # sum_cols first, then max_cols, then keep_id (positional access).
            select_parts = (
                [f"COALESCE(SUM({c}),0)" for c in sum_cols]
                + [f"MAX({c})" for c in max_cols]
                + ["MAX(id)"]
            )
            async with conn.execute(
                f"SELECT {', '.join(select_parts)} FROM {table} WHERE {where_clause}",
                key_vals,
            ) as cur:
                row = await cur.fetchone()
            if not row:
                continue

            n_sum = len(sum_cols)
            n_max = len(max_cols)
            sum_vals = list(row[:n_sum])
            max_vals = list(row[n_sum : n_sum + n_max])
            keep_id = row[n_sum + n_max]

            set_pairs = [f"{c}=?" for c in sum_cols] + [f"{c}=?" for c in max_cols]
            await conn.execute(
                f"UPDATE {table} SET {', '.join(set_pairs)} WHERE id=?",
                (*sum_vals, *max_vals, keep_id),
            )
            await conn.execute(
                f"DELETE FROM {table} WHERE {where_clause} AND id<>?",
                (*key_vals, keep_id),
            )

        if groups:
            await conn.commit()
            logger.info("Migration: deduped %d group(s) in %s", len(groups), table)

        # Now create the unique index (no-op if it exists or if a UNIQUE constraint
        # is already enforced via CREATE TABLE).
        try:
            idx_cols = ", ".join(key_cols)
            await conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAMES[table]} "
                f"ON {table}({idx_cols})"
            )
            await conn.commit()
        except Exception as e:
            logger.warning("Migration: index create failed for %s: %s", table, e)


def _py_lower(s: str | None) -> str | None:
    """Unicode-aware LOWER for SQLite — handles Cyrillic that built-in LOWER() ignores."""
    return s.lower() if s else s


@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Async context manager — yields an open aiosqlite connection."""
    async with aiosqlite.connect(settings.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.create_function("py_lower", 1, _py_lower)
        yield conn
