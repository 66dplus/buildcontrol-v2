"""
Deletes ALL projects (workgroups), their tasks, and their universal lists from Bitrix24.

Usage:
    python scripts/cleanup_bitrix.py             # dry-run (prints what would be deleted)
    python scripts/cleanup_bitrix.py --confirm   # actually deletes everything
"""

import asyncio
import logging
import sys
from typing import Any

from bitrix.client import BitrixClient
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DRY_RUN = "--confirm" not in sys.argv


async def list_all_groups(client: BitrixClient) -> list[dict[str, Any]]:
    """Return all workgroups (both active and closed)."""
    result = await client.call("sonet_group.get", {
        "SELECT": ["ID", "NAME"],
    })
    raw = result.get("result", [])
    return [{"id": int(g["ID"]), "name": g["NAME"]} for g in raw]


async def list_all_tasks(client: BitrixClient, group_id: int) -> list[int]:
    """Return all task IDs in a project (paginated)."""
    task_ids: list[int] = []
    start = 0
    while True:
        resp = await client.call("tasks.task.list", {
            "filter": {"GROUP_ID": group_id},
            "select": ["ID"],
            "start": start,
        })
        result_obj = resp.get("result", {})
        tasks_list = result_obj.get("tasks", []) if isinstance(result_obj, dict) else result_obj
        for t in tasks_list:
            try:
                task_ids.append(int(t.get("id") or t.get("ID")))
            except (TypeError, ValueError):
                pass
        next_start = resp.get("next")
        if next_start is None:
            break
        start = int(next_start)
    return task_ids


async def list_all_lists(client: BitrixClient, group_id: int) -> list[dict[str, Any]]:
    """Return all universal lists for a workgroup."""
    resp = await client.call("lists.get", {
        "IBLOCK_TYPE_ID": "lists_socnet",
        "SOCNET_GROUP_ID": group_id,
    })
    raw = resp.get("result", [])
    return [{"id": int(lst["ID"]), "name": lst.get("NAME", "")} for lst in raw]


async def delete_task(client: BitrixClient, task_id: int) -> None:
    await client.call("tasks.task.delete", {"taskId": task_id})


async def delete_list(client: BitrixClient, list_id: int, group_id: int) -> None:
    await client.call("lists.delete", {
        "IBLOCK_TYPE_ID": "lists_socnet",
        "IBLOCK_ID": list_id,
        "SOCNET_GROUP_ID": group_id,
    })


async def delete_group(client: BitrixClient, group_id: int) -> None:
    await client.call("sonet_group.delete", {"GROUP_ID": group_id})


async def cleanup(client: BitrixClient) -> None:
    logger.info("Fetching all workgroups...")
    groups = await list_all_groups(client)

    if not groups:
        logger.info("No workgroups found. Nothing to delete.")
        return

    logger.info(f"Found {len(groups)} workgroup(s):")
    for g in groups:
        logger.info(f"  [{g['id']}] {g['name']}")

    if DRY_RUN:
        logger.warning("DRY RUN — no changes made. Re-run with --confirm to delete.")
        return

    for group in groups:
        gid = group["id"]
        gname = group["name"]
        logger.info(f"\n--- Processing project [{gid}] {gname} ---")

        # Delete tasks
        task_ids = await list_all_tasks(client, gid)
        logger.info(f"  Deleting {len(task_ids)} task(s)...")
        for tid in task_ids:
            try:
                await delete_task(client, tid)
                logger.info(f"    Deleted task {tid}")
            except Exception as e:
                logger.warning(f"    Failed to delete task {tid}: {e}")

        # Delete universal lists
        lists = await list_all_lists(client, gid)
        logger.info(f"  Deleting {len(lists)} list(s)...")
        for lst in lists:
            try:
                await delete_list(client, lst["id"], gid)
                logger.info(f"    Deleted list [{lst['id']}] {lst['name']}")
            except Exception as e:
                logger.warning(f"    Failed to delete list {lst['id']}: {e}")

        # Delete the workgroup itself
        try:
            await delete_group(client, gid)
            logger.info(f"  Deleted workgroup [{gid}] {gname}")
        except Exception as e:
            logger.warning(f"  Failed to delete workgroup {gid}: {e}")

    logger.info("\nCleanup complete.")


async def main() -> None:
    settings.validate()
    if DRY_RUN:
        logger.warning("Running in DRY RUN mode (use --confirm to actually delete).")

    async with BitrixClient() as client:
        await cleanup(client)


if __name__ == "__main__":
    asyncio.run(main())
