"""
Workgroups and Projects methods wrapper for Bitrix24 REST API.
"""

from typing import Any, Dict, List, Optional

from bitrix.client import BitrixClient


async def create_project(
    client: BitrixClient,
    name: str,
    description: Optional[str] = None,
    owner_id: Optional[int] = None,
    visible: bool = True,
) -> int:
    """
    Create a new project (workgroup with PROJECT flag).

    Args:
        client: BitrixClient instance
        name: Project name
        description: Optional project description
        owner_id: Optional project owner user ID
        visible: Whether project is visible to all users

    Returns:
        Created project ID

    Raises:
        ValueError: If API call fails
    """
    params: Dict[str, Any] = {
        "NAME": name,
        "PROJECT": "Y",
        "VISIBLE": "Y" if visible else "N",
    }

    if description:
        params["DESCRIPTION"] = description

    if owner_id:
        params["OWNER_ID"] = owner_id

    result = await client.call("sonet_group.create", params)
    return result["result"]


async def list_projects(client: BitrixClient) -> List[Dict[str, Any]]:
    """
    List all active projects (workgroups).

    Returns:
        List of dicts with 'id' and 'name' keys.
    """
    result = await client.call("sonet_group.get", {
        "FILTER": {"ACTIVE": "Y", "CLOSED": "N"},
        "ORDER": {"NAME": "ASC"},
        "SELECT": ["ID", "NAME"],
    })
    raw = result.get("result", [])
    return [{"id": int(g["ID"]), "name": g["NAME"]} for g in raw]
