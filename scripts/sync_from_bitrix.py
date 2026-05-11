"""
CLI: pull Bitrix24 workgroups + lists into local SQLite.

Usage:
    python scripts/sync_from_bitrix.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import get_db, init_db
from app.services.sync_from_bitrix import sync_all_projects


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    await init_db()
    async with get_db() as conn:
        result = await sync_all_projects(conn)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
