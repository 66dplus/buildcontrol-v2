"""
Universal Lists methods wrapper for Bitrix24 REST API.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from bitrix.client import BitrixClient

logger = logging.getLogger(__name__)


async def create_list(
    client: BitrixClient,
    name: str,
    group_id: int,
    iblock_code: str,
    description: Optional[str] = None,
) -> int:
    """
    Create a new Universal List inside a project/workgroup.

    Args:
        client: BitrixClient instance
        name: List name
        group_id: Project/workgroup ID (SOCNET_GROUP_ID)
        iblock_code: Unique code for this list (e.g. 'bc_4_budget')
        description: Optional list description

    Returns:
        Created list ID (iblock_id)

    Raises:
        ValueError: If API call fails
    """
    params: Dict[str, Any] = {
        "IBLOCK_TYPE_ID": "lists_socnet",
        "IBLOCK_CODE": iblock_code,
        "SOCNET_GROUP_ID": group_id,
        "FIELDS": {
            "NAME": name,
            "DESCRIPTION": description or "",
        },
    }

    result = await client.call("lists.add", params)
    return result["result"]


async def add_field(
    client: BitrixClient,
    list_id: int,
    iblock_code: str,
    group_id: int,
    name: str,
    field_code: str,
    field_type: str,
    sort: int = 10,
    required: bool = False,
) -> int:
    """
    Add a custom field to a list.

    Args:
        client: BitrixClient instance
        list_id: List ID (iblock_id)
        iblock_code: List code (same used in create_list)
        group_id: Project/workgroup ID
        name: Field display name
        field_code: Unique code for this field (e.g. 'qty_plan')
        field_type: Field type: S=string, N=number, S:Date=date, S:Money=money
        sort: Sort order
        required: Whether field is required

    Returns:
        Created field ID (used as PROPERTY_<id> in elements)

    Raises:
        ValueError: If API call fails
    """
    params: Dict[str, Any] = {
        "IBLOCK_TYPE_ID": "lists_socnet",
        "IBLOCK_ID": list_id,
        "IBLOCK_CODE": iblock_code,
        "SOCNET_GROUP_ID": group_id,
        "FIELDS": {
            "NAME": name,
            "CODE": field_code,
            "TYPE": field_type,
            "SORT": str(sort),
            "IS_REQUIRED": "Y" if required else "N",
            "MULTIPLE": "N",
            "SETTINGS": {
                "SHOW_ADD_FORM": "Y",
                "SHOW_EDIT_FORM": "Y",
                "ADD_READ_ONLY_FIELD": "N",
                "EDIT_READ_ONLY_FIELD": "N",
                "SHOW_FIELD_PREVIEW": "N",
            },
        },
    }

    result = await client.call("lists.field.add", params)
    # API returns "PROPERTY_98" — extract the numeric ID
    raw = result["result"]  # e.g. "PROPERTY_98"
    return int(str(raw).split("_")[-1])


async def add_element(
    client: BitrixClient,
    list_id: int,
    iblock_code: str,
    group_id: int,
    element_code: str,
    name: str,
    field_values: Dict[int, Any],
) -> int:
    """
    Add an element (row) to a list.

    Args:
        client: BitrixClient instance
        list_id: List ID
        iblock_code: List code
        group_id: Project/workgroup ID
        element_code: Unique code for this element (e.g. 'row_1')
        name: Element name (displayed in list)
        field_values: Dict of {field_id: value} — field_id from add_field()

    Returns:
        Created element ID

    Raises:
        ValueError: If API call fails
    """
    fields: Dict[str, Any] = {"NAME": name}
    for field_id, value in field_values.items():
        if value is not None:
            if hasattr(value, "isoformat"):
                # datetime → "2026-06-01"
                value = value.date().isoformat() if hasattr(value, "date") else str(value)
            elif isinstance(value, float) and value == int(value):
                # 320.0 → "320" (not "320.0")
                value = int(value)
            fields[f"PROPERTY_{field_id}"] = str(value)

    params: Dict[str, Any] = {
        "IBLOCK_TYPE_ID": "lists_socnet",
        "IBLOCK_ID": list_id,
        "IBLOCK_CODE": iblock_code,
        "SOCNET_GROUP_ID": group_id,
        "ELEMENT_CODE": element_code,
        "FIELDS": fields,
    }

    result = await client.call("lists.element.add", params)
    return result["result"]


# ---------------------------------------------------------------------------
# Read methods (for foreman report)
# ---------------------------------------------------------------------------


async def get_lists(
    client: BitrixClient,
    group_id: int,
) -> List[Dict[str, Any]]:
    """
    Get all Universal Lists in a project/workgroup.

    Returns:
        List of list dicts with ID, NAME, IBLOCK_CODE, etc.
    """
    result = await client.call("lists.get", {
        "IBLOCK_TYPE_ID": "lists_socnet",
        "SOCNET_GROUP_ID": group_id,
    })
    raw = result.get("result", [])
    if isinstance(raw, dict):
        # Single list returned as dict instead of array
        raw = [raw]
    return raw


async def get_fields(
    client: BitrixClient,
    list_id: int,
    iblock_code: str,
    group_id: int,
) -> Dict[str, Dict[str, Any]]:
    """
    Get all fields of a list.

    Returns:
        Dict mapping field_id (e.g. "PROPERTY_98") to field definition dict
        with keys like NAME, TYPE, SORT, etc.
    """
    result = await client.call("lists.field.get", {
        "IBLOCK_TYPE_ID": "lists_socnet",
        "IBLOCK_ID": list_id,
        "IBLOCK_CODE": iblock_code,
        "SOCNET_GROUP_ID": group_id,
    })
    return result.get("result", {})


async def get_elements(
    client: BitrixClient,
    list_id: int,
    iblock_code: str,
    group_id: int,
) -> List[Dict[str, Any]]:
    """
    Get all elements (rows) from a list.

    Returns:
        List of element dicts with ID, NAME, and PROPERTY_XX values.
    """
    result = await client.call("lists.element.get", {
        "IBLOCK_TYPE_ID": "lists_socnet",
        "IBLOCK_ID": list_id,
        "IBLOCK_CODE": iblock_code,
        "SOCNET_GROUP_ID": group_id,
    })
    raw = result.get("result", [])
    if isinstance(raw, dict):
        raw = [raw]
    return raw


async def update_element(
    client: BitrixClient,
    list_id: int,
    iblock_code: str,
    group_id: int,
    element_id: int,
    field_values: Dict[int, Any],
    name: Optional[str] = None,
) -> bool:
    """
    Update an existing list element's field values.

    Args:
        client: BitrixClient instance
        list_id: List ID
        iblock_code: List code
        group_id: Project/workgroup ID
        element_id: ID of the element to update
        field_values: Dict of {field_id: new_value}

    Returns:
        True on success

    Raises:
        ValueError: If API call fails
    """
    fields: Dict[str, Any] = {}
    if name:
        fields["NAME"] = name
    for field_id, value in field_values.items():
        if value is not None:
            if hasattr(value, "isoformat"):
                value = value.date().isoformat() if hasattr(value, "date") else str(value)
            elif isinstance(value, float) and value == int(value):
                value = int(value)
            fields[f"PROPERTY_{field_id}"] = str(value)

    params: Dict[str, Any] = {
        "IBLOCK_TYPE_ID": "lists_socnet",
        "IBLOCK_ID": list_id,
        "IBLOCK_CODE": iblock_code,
        "SOCNET_GROUP_ID": group_id,
        "ELEMENT_ID": element_id,
        "FIELDS": fields,
    }

    result = await client.call("lists.element.update", params)
    return bool(result.get("result"))


def extract_all_prop_values(element: Dict[str, Any]) -> Dict[int, Any]:
    """
    Extract ALL PROPERTY_XX values from an element dict as {prop_id: raw_value}.

    Used to build a full field set before calling update_element, so that
    Bitrix24 does not clear unspecified properties on update.
    """
    result: Dict[int, Any] = {}
    for key, val in element.items():
        if key.startswith("PROPERTY_"):
            prop_id = int(key.split("_")[-1])
            if isinstance(val, dict):
                val = next(iter(val.values()), None)
            if val is not None and str(val).strip() != "":
                result[prop_id] = val
    return result


def resolve_field_map(fields_response: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """
    Build a field_name → property_id mapping from get_fields() response.

    Args:
        fields_response: Return value of get_fields()

    Returns:
        Dict mapping field NAME (display name) to numeric property ID.
        E.g. {"Объём куплено": 42, "Стоимость куплено, ₽": 43, ...}
    """
    result: Dict[str, int] = {}
    for fid, fdef in fields_response.items():
        if fid.startswith("PROPERTY_"):
            name = fdef.get("NAME", "")
            if name:
                result[name] = int(fid.split("_")[-1])
    return result


def list_name_matches(list_name: str, keyword: str) -> bool:
    """
    Match a Universal List name by keyword with hierarchy-aware exclusions.

    Important: "подзадачи" contains "задач", so when searching for "задач"
    we must explicitly exclude the subtasks list.
    """
    name_lower = (list_name or "").lower()
    keyword_lower = (keyword or "").strip().lower()
    if not keyword_lower:
        return False

    if keyword_lower == "задач":
        return "задач" in name_lower and "подзадач" not in name_lower

    return keyword_lower in name_lower


def find_list_by_keyword(
    all_lists: List[Dict[str, Any]],
    keyword: str,
) -> Optional[Dict[str, Any]]:
    """Return the first list matching keyword rules."""
    for lst in all_lists:
        if list_name_matches(lst.get("NAME", ""), keyword):
            return lst
    return None


def find_element_by_name(elements: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    """
    Find a list element by its NAME field (case-insensitive strip).

    Args:
        elements: Return value of get_elements()
        name: Element name to search for

    Returns:
        Element dict or None if not found
    """
    name_lower = name.strip().lower()
    for elem in elements:
        if elem.get("NAME", "").strip().lower() == name_lower:
            return elem
    return None


def get_prop_value(element: Dict[str, Any], prop_id: int) -> Optional[float]:
    """
    Extract a numeric property value from an element dict.

    Bitrix24 returns property values as dicts like {"0": "42.5"} or plain strings.

    Returns:
        Float value or None if missing/blank
    """
    raw = element.get(f"PROPERTY_{prop_id}")
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = next(iter(raw.values()), None)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


async def get_or_create_report_list(
    client: BitrixClient,
    group_id: int,
) -> Dict[str, Any]:
    """
    Get or create the "Отчеты прораба" report list for a project.

    Returns:
        Dict with 'list_id', 'iblock_code', and 'field_ids' mapping.
    """
    base_iblock_code = f"bc_{group_id}_reports"

    # Check if list already exists — match by name (resilient to iblock_code reuse after deletion)
    all_lists = await get_lists(client, group_id)
    for lst in all_lists:
        if "отчет" in lst.get("NAME", "").lower():
            list_id = int(lst["ID"])
            iblock_code = lst.get("IBLOCK_CODE", base_iblock_code)
            fields = await get_fields(client, list_id, iblock_code, group_id)
            field_ids = {}
            for fid, fdef in fields.items():
                if fid.startswith("PROPERTY_"):
                    code = fdef.get("CODE", "")
                    if code:
                        field_ids[code] = int(fid.split("_")[-1])
            logger.info(f"Found existing report list ID={list_id} for project {group_id}")
            return {"list_id": list_id, "iblock_code": iblock_code, "field_ids": field_ids}

    # Create list — retry with counter suffix if iblock_code slot is still taken in Bitrix24
    list_id: Optional[int] = None
    iblock_code = base_iblock_code
    for attempt in range(1, 6):
        code = base_iblock_code if attempt == 1 else f"{base_iblock_code}_{attempt}"
        try:
            list_id = await create_list(
                client,
                name="Отчеты прораба",
                group_id=group_id,
                iblock_code=code,
                description="Ежедневные отчеты прораба",
            )
            iblock_code = code
            break
        except ValueError as e:
            if "already exist" in str(e).lower():
                logger.warning(f"iblock_code '{code}' taken, retrying with next suffix…")
                continue
            raise
    if list_id is None:
        raise ValueError(f"Cannot create report list for project {group_id}: all iblock_code slots taken")

    # Create fields
    report_fields = [
        ("f_0_date", "Дата отчета", "S:Date"),
        ("f_1_author", "Автор", "S"),
        ("f_2_comments", "Комментарий", "S"),
        ("f_3_materials", "Материалы (JSON)", "S"),
        ("f_4_labor", "Трудозатраты (JSON)", "S"),
    ]

    field_ids: Dict[str, int] = {}
    for sort_idx, (code, name, field_type) in enumerate(report_fields):
        fid = await add_field(
            client,
            list_id=list_id,
            iblock_code=iblock_code,
            group_id=group_id,
            name=name,
            field_code=code,
            field_type=field_type,
            sort=(sort_idx + 1) * 10,
        )
        field_ids[code] = fid

    logger.info(f"Created report list ID={list_id} for project {group_id}")
    return {"list_id": list_id, "iblock_code": iblock_code, "field_ids": field_ids}


PURCHASE_REQUEST_LIST_KEYWORD = "заявк"
PURCHASE_REQUEST_FIELDS = [
    ("f_pr_no", "№ заявки", "N"),
    ("f_pr_date", "Дата", "S:Date"),
    ("f_pr_author", "Автор", "S"),
    ("f_pr_etap", "Этап", "S"),
    ("f_pr_zadacha", "Задача", "S"),
    ("f_pr_material", "Материал", "S"),
    ("f_pr_qty", "Кол-во", "N"),
    ("f_pr_unit", "Ед. изм.", "S"),
    ("f_pr_price", "Цена ед., ₽", "N"),
    ("f_pr_total", "Стоимость, ₽", "N"),
    ("f_pr_file_url", "Файл (URL)", "S"),
    ("f_pr_status", "Статус", "S"),
    ("f_pr_btask_id", "ID задачи Bitrix", "N"),
    ("f_pr_material_eid", "ID элемента Материалы", "N"),
    ("f_pr_comment", "Комментарий", "S"),
    ("f_pr_history", "История JSON", "S"),
]


async def get_or_create_purchase_requests_list(
    client: BitrixClient,
    group_id: int,
) -> Dict[str, Any]:
    """
    Get or create the "Заявки на закупку" list for a project (idempotent).

    Returns:
        Dict with 'list_id', 'iblock_code', 'field_ids' (code → property id), and
        'field_map' (display name → property id).
    """
    base_iblock_code = f"bc_{group_id}_purchase_requests"

    all_lists_resp = await get_lists(client, group_id)
    for lst in all_lists_resp:
        if PURCHASE_REQUEST_LIST_KEYWORD in lst.get("NAME", "").lower():
            list_id = int(lst["ID"])
            iblock_code = lst.get("IBLOCK_CODE", base_iblock_code)
            fields_resp = await get_fields(client, list_id, iblock_code, group_id)
            field_ids: Dict[str, int] = {}
            field_map: Dict[str, int] = {}
            for fid, fdef in fields_resp.items():
                if fid.startswith("PROPERTY_"):
                    pid = int(fid.split("_")[-1])
                    code = fdef.get("CODE", "")
                    if code:
                        field_ids[code] = pid
                    name = fdef.get("NAME", "")
                    if name:
                        field_map[name] = pid
            logger.info(f"Found existing purchase-requests list ID={list_id} for project {group_id}")
            return {
                "list_id": list_id,
                "iblock_code": iblock_code,
                "field_ids": field_ids,
                "field_map": field_map,
            }

    list_id: Optional[int] = None
    iblock_code = base_iblock_code
    for attempt in range(1, 6):
        code = base_iblock_code if attempt == 1 else f"{base_iblock_code}_{attempt}"
        try:
            list_id = await create_list(
                client,
                name="Заявки на закупку",
                group_id=group_id,
                iblock_code=code,
                description="Заявки закупщика на согласование",
            )
            iblock_code = code
            break
        except ValueError as e:
            if "already exist" in str(e).lower():
                logger.warning(f"iblock_code '{code}' taken, retrying with next suffix…")
                continue
            raise
    if list_id is None:
        raise ValueError(
            f"Cannot create purchase-requests list for project {group_id}: all iblock_code slots taken"
        )

    field_ids = {}
    field_map = {}
    for sort_idx, (code, name, field_type) in enumerate(PURCHASE_REQUEST_FIELDS):
        try:
            pid = await add_field(
                client,
                list_id=list_id,
                iblock_code=iblock_code,
                group_id=group_id,
                name=name,
                field_code=code,
                field_type=field_type,
                sort=(sort_idx + 1) * 10,
            )
            field_ids[code] = pid
            field_map[name] = pid
        except ValueError as e:
            logger.warning(f"Failed to create purchase-request field '{name}': {e}")

    logger.info(f"Created purchase-requests list ID={list_id} for project {group_id}")
    return {
        "list_id": list_id,
        "iblock_code": iblock_code,
        "field_ids": field_ids,
        "field_map": field_map,
    }


# ---------------------------------------------------------------------------
# Helpers for v3 hierarchy (text-based FK matching & aggregation)
# ---------------------------------------------------------------------------


def get_prop_value_str(element: Dict[str, Any], prop_id: int) -> Optional[str]:
    """
    Extract a string property value from an element dict.

    Like get_prop_value but returns str instead of float — used for text FK
    matching on Этап/Задача columns.
    """
    raw = element.get(f"PROPERTY_{prop_id}")
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = next(iter(raw.values()), None)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip()


def _resolve_filter_pid(field_map: Dict[str, int], keyword: str) -> Optional[int]:
    """Find property ID whose field name contains the keyword (case-insensitive)."""
    kw = keyword.lower()
    for fname, pid in field_map.items():
        if kw in fname.lower():
            return pid
    return None


def find_elements_by_properties(
    elements: List[Dict[str, Any]],
    field_map: Dict[str, int],
    filters: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Filter elements where all specified property values match.

    Args:
        elements: List of element dicts from get_elements()
        field_map: field_name → property_id mapping from resolve_field_map()
        filters: Dict of {field_keyword: expected_value}
            e.g. {"Этап": "Фундамент", "Задача": "Устройство подушки"}

    Returns:
        List of matching elements.
    """
    # Resolve keywords to property IDs
    resolved: List[tuple[int, str]] = []
    for keyword, expected in filters.items():
        pid = _resolve_filter_pid(field_map, keyword)
        if pid is None:
            return []  # Can't filter on unknown field
        resolved.append((pid, expected.strip().lower()))

    result: List[Dict[str, Any]] = []
    for elem in elements:
        match = True
        for pid, expected_lower in resolved:
            actual = get_prop_value_str(elem, pid)
            if actual is None or actual.lower() != expected_lower:
                match = False
                break
        if match:
            result.append(elem)
    return result


def sum_prop_values(
    elements: List[Dict[str, Any]],
    field_map: Dict[str, int],
    field_keyword: str,
) -> float:
    """
    Sum a numeric property across a list of elements.

    Args:
        elements: List of element dicts
        field_map: field_name → property_id mapping
        field_keyword: Keyword to match the field name (e.g. "стоим. факт")

    Returns:
        Sum of the property values (0.0 if field not found or all empty).
    """
    pid = _resolve_filter_pid(field_map, field_keyword)
    if pid is None:
        return 0.0
    total = 0.0
    for elem in elements:
        val = get_prop_value(elem, pid)
        if val is not None:
            total += val
    return total
