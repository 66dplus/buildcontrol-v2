"""
Bitrix24 Disk methods wrapper.

Used by the procurement approval flow to attach commercial-proposal documents
to the audit task for each purchase request.
"""

import base64
import logging
from typing import Any, Dict, List, Optional

from bitrix.client import BitrixClient

logger = logging.getLogger(__name__)


async def get_workgroup_storage(client: BitrixClient, group_id: int) -> Optional[Dict[str, Any]]:
    """Return the disk storage object for a workgroup, or None if not found."""
    resp = await client.call("disk.storage.getlist", {
        "filter": {"ENTITY_TYPE": "group", "ENTITY_ID": group_id},
    })
    raw = resp.get("result") or []
    if isinstance(raw, dict):
        raw = [raw]
    return raw[0] if raw else None


async def get_or_create_subfolder(
    client: BitrixClient, parent_folder_id: int, name: str,
) -> int:
    """Return id of a child folder named ``name`` under ``parent_folder_id``, creating it if missing."""
    resp = await client.call("disk.folder.getchildren", {"id": parent_folder_id})
    children = resp.get("result") or []
    if isinstance(children, dict):
        children = [children]
    for child in children:
        if str(child.get("TYPE", "")).lower() == "folder" and str(child.get("NAME", "")).strip() == name.strip():
            return int(child["ID"])

    create_resp = await client.call("disk.folder.addsubfolder", {
        "id": parent_folder_id,
        "data": {"NAME": name},
    })
    return int(create_resp["result"]["ID"])


async def upload_file_to_workgroup(
    client: BitrixClient,
    group_id: int,
    folder_name: str,
    filename: str,
    content: bytes,
) -> Dict[str, Any]:
    """
    Upload ``content`` as ``filename`` into ``<workgroup disk>/<folder_name>/``.

    Returns the disk file object: ``{ID, NAME, DOWNLOAD_URL, ...}``.
    """
    storage = await get_workgroup_storage(client, group_id)
    if not storage:
        raise ValueError(f"Bitrix24 disk storage not found for workgroup {group_id}")

    root_folder_id = int(storage.get("ROOT_OBJECT_ID") or storage.get("ROOT_FOLDER_ID") or 0)
    if not root_folder_id:
        raise ValueError(f"Workgroup {group_id} disk storage has no ROOT_OBJECT_ID")

    folder_id = await get_or_create_subfolder(client, root_folder_id, folder_name)

    encoded = base64.b64encode(content).decode("ascii")
    resp = await client.call("disk.folder.uploadfile", {
        "id": folder_id,
        "data": {"NAME": filename},
        "fileContent": [filename, encoded],
        "generateUniqueName": "Y",
    })
    file_obj = resp.get("result") or {}
    if isinstance(file_obj, dict) and file_obj.get("ID"):
        logger.info(
            f"Uploaded '{filename}' ({len(content)} bytes) to workgroup {group_id} "
            f"folder '{folder_name}' as file {file_obj['ID']}"
        )
        return file_obj
    raise ValueError(f"Bitrix24 disk upload returned no file ID: {resp!r}")


def task_webdav_files_value(file_ids: List[int]) -> List[str]:
    """
    Format disk file IDs for the ``UF_TASK_WEBDAV_FILES`` task field.

    Bitrix24 expects each value as ``"n<id>"`` (the legacy "new attachment" prefix
    is required even for already-uploaded files).
    """
    return [f"n{int(fid)}" for fid in file_ids]
