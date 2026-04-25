"""
Procurement approval flow.

Buyer submits a purchase request (material + qty + price + counterparty document).
The request is recorded in the project's "Заявки на закупку" universal list and an
audit task is opened in Bitrix24 with a link to the approval page hosted by this
app. The approver decides Approve / Reject / Comment from either the page or
Telegram inline buttons; both paths route through ``resolve_request`` here.

Only after Approve do warehouse fact + weighted price update on "3. Материалы"
— the same math the legacy buyer-report endpoint used.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from bitrix.client import BitrixClient
from bitrix.methods import disk as disk_methods
from bitrix.methods import lists, tasks as tasks_methods, workgroups
from config import settings

logger = logging.getLogger(__name__)


STATUS_PENDING = "Ожидает"
STATUS_APPROVED = "Подтверждено"
STATUS_REJECTED = "Отклонено"

DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
DECISION_COMMENT = "comment"

SOURCE_PAGE = "page"
SOURCE_TELEGRAM = "telegram"

DISK_FOLDER_NAME = "Заявки на закупку"

# Tiny TTL cache for cross-project material counts.
_MATERIAL_USAGE_CACHE: Dict[str, Tuple[float, Dict[str, int]]] = {}
_MATERIAL_USAGE_TTL_SECONDS = 300.0


# ---------------------------------------------------------------------------
# Token signing
# ---------------------------------------------------------------------------


def make_token(request_id: int) -> str:
    """Sign ``request_id`` with the configured HMAC secret."""
    secret = (settings.approval_link_secret or "").encode("utf-8")
    if not secret:
        logger.warning("APPROVAL_LINK_SECRET not configured — tokens will not be verifiable")
    digest = hmac.new(secret, str(int(request_id)).encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:32]


def verify_token(request_id: int, token: str) -> bool:
    """Constant-time check that ``token`` matches ``request_id``."""
    if not token:
        return False
    expected = make_token(request_id)
    return hmac.compare_digest(expected, token)


def approval_url(request_id: int) -> str:
    base = (settings.vps_url or "").rstrip("/")
    qs = urlencode({"token": make_token(request_id)})
    return f"{base}/approval/{int(request_id)}?{qs}"


# ---------------------------------------------------------------------------
# List row helpers
# ---------------------------------------------------------------------------


def _row_to_request(elem: Dict[str, Any], field_ids: Dict[str, int]) -> Dict[str, Any]:
    """Decode a list element into a request dict."""
    def _str(code: str) -> Optional[str]:
        pid = field_ids.get(code)
        if not pid:
            return None
        return lists.get_prop_value_str(elem, pid)

    def _num(code: str) -> Optional[float]:
        pid = field_ids.get(code)
        if not pid:
            return None
        return lists.get_prop_value(elem, pid)

    history_raw = _str("f_pr_history") or "[]"
    try:
        history = json.loads(history_raw)
    except json.JSONDecodeError:
        history = []

    items_raw = _str("f_pr_material") or ""
    items: List[Dict[str, Any]] = []
    if items_raw.startswith("["):
        try:
            items = json.loads(items_raw)
        except json.JSONDecodeError:
            items = []
    if not items:
        items = [{
            "material_name": items_raw,
            "qty": _num("f_pr_qty") or 0,
            "unit": _str("f_pr_unit") or "",
            "price": _num("f_pr_price") or 0,
            "total": _num("f_pr_total") or 0,
        }]

    return {
        "id": int(elem["ID"]),
        "name": elem.get("NAME", ""),
        "no": int(_num("f_pr_no") or 0),
        "date": _str("f_pr_date"),
        "author": _str("f_pr_author") or "",
        "etap": _str("f_pr_etap") or "",
        "zadacha": _str("f_pr_zadacha") or "",
        "items": items,
        "file_url": _str("f_pr_file_url") or "",
        "status": _str("f_pr_status") or STATUS_PENDING,
        "bitrix_task_id": int(_num("f_pr_btask_id") or 0),
        "comment": _str("f_pr_comment") or "",
        "history": history,
    }


def _items_total(items: List[Dict[str, Any]]) -> float:
    return float(sum(float(it.get("total") or (float(it.get("qty") or 0) * float(it.get("price") or 0))) for it in items))


def _next_request_no(elements: List[Dict[str, Any]], pid_no: Optional[int]) -> int:
    if not pid_no:
        return len(elements) + 1
    max_no = 0
    for elem in elements:
        val = lists.get_prop_value(elem, pid_no)
        if val:
            try:
                max_no = max(max_no, int(val))
            except (TypeError, ValueError):
                pass
    return max_no + 1


# ---------------------------------------------------------------------------
# Price-deviation severity helper (shared between Telegram + approval views)
# ---------------------------------------------------------------------------


def format_price_deviation(price: float, price_plan: float, qty: float) -> Dict[str, Any]:
    """
    Grade the deviation of buyer's actual price vs the planned price for one item.

    Severity bands (positive deviation only — negative means saving):
        ≤ 0%       → "ok"        ✅  no warning
        0 < x ≤ 2  → "low"       🟡
        2 < x ≤ 5  → "medium"    🟠 ОБРАТИТЕ ВНИМАНИЕ
        5 < x ≤ 10 → "high"      🔴 ВНИМАНИЕ
        > 10%      → "critical"  🚨 КРИТИЧЕСКОЕ ПРЕВЫШЕНИЕ ПЛАНА

    Returns a dict with ``severity``, ``emoji``, ``header`` (may be ""), ``body``
    (one-line plain-Russian message), and ``dev_pct``/``overspend`` for callers
    that want raw numbers. ``severity == "none"`` means no plan price was found.
    """
    if not price_plan or price_plan <= 0:
        return {"severity": "none", "emoji": "", "header": "", "body": "",
                "dev_pct": None, "overspend": 0.0}

    dev_pct = (price - price_plan) / price_plan * 100.0
    overspend = (price - price_plan) * float(qty or 0)

    if dev_pct <= 0:
        return {
            "severity": "ok", "emoji": "✅", "header": "",
            "body": f"Цена в рамках плана (план {price_plan:.2f} ₽, факт {price:.2f} ₽)",
            "dev_pct": dev_pct, "overspend": overspend,
        }

    if dev_pct <= 2:
        sev, emoji, header = "low", "🟡", ""
    elif dev_pct <= 5:
        sev, emoji, header = "medium", "🟠", "ОБРАТИТЕ ВНИМАНИЕ"
    elif dev_pct <= 10:
        sev, emoji, header = "high", "🔴", "ВНИМАНИЕ"
    else:
        sev, emoji, header = "critical", "🚨", "КРИТИЧЕСКОЕ ПРЕВЫШЕНИЕ ПЛАНА"

    overspend_str = f"{overspend:,.0f}".replace(",", " ")
    body = (
        f"Цена превышает план на {dev_pct:.1f}%. "
        f"Перерасход составит {overspend_str} ₽ "
        f"(план {price_plan:.2f} ₽, факт {price:.2f} ₽)."
    )
    return {
        "severity": sev, "emoji": emoji, "header": header, "body": body,
        "dev_pct": dev_pct, "overspend": overspend,
    }


# ---------------------------------------------------------------------------
# Material context (cross-project)
# ---------------------------------------------------------------------------


async def _fetch_material_usage(
    client: BitrixClient, material_name: str,
) -> Dict[str, int]:
    """
    Walk all active workgroups and count those that have ``material_name``
    "in active use" or "planned for the future".
    """
    cache_key = material_name.strip().lower()
    cached = _MATERIAL_USAGE_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]

    active = 0
    future = 0
    try:
        projects = await workgroups.list_projects(client)
    except Exception as e:
        logger.warning(f"material_context: list_projects failed: {e}")
        projects = []

    for proj in projects:
        gid = int(proj["id"])
        try:
            all_lists = await lists.get_lists(client, gid)
            target = lists.find_list_by_keyword(all_lists, "материал")
            if not target:
                continue
            list_id = int(target["ID"])
            iblock_code = target.get("IBLOCK_CODE", "")
            fields_resp = await lists.get_fields(client, list_id, iblock_code, gid)
            field_map = lists.resolve_field_map(fields_resp)
            elements = await lists.get_elements(client, list_id, iblock_code, gid)
        except Exception as e:
            logger.debug(f"material_context: project {gid} skipped: {e}")
            continue

        elem = lists.find_element_by_name(elements, material_name)
        if not elem:
            continue

        pid_plan = lists._resolve_filter_pid(field_map, "объём план")
        pid_bought = next(
            (pid for n, pid in field_map.items() if "куплено" in n.lower() and "объём" in n.lower()),
            None,
        )
        pid_used = lists._resolve_filter_pid(field_map, "израсходовано")

        plan = float(lists.get_prop_value(elem, pid_plan) or 0) if pid_plan else 0.0
        bought = float(lists.get_prop_value(elem, pid_bought) or 0) if pid_bought else 0.0
        used = float(lists.get_prop_value(elem, pid_used) or 0) if pid_used else 0.0

        if bought > 0 or used > 0:
            active += 1
        if plan > 0 and used == 0:
            future += 1

    result = {"active_projects": active, "future_projects": future}
    _MATERIAL_USAGE_CACHE[cache_key] = (now + _MATERIAL_USAGE_TTL_SECONDS, result)
    return result


async def material_context(
    client: BitrixClient,
    project_id: int,
    material_name: str,
    qty: float,
    price: float,
) -> Dict[str, Any]:
    """
    Build the rich context block shown on the approval page and Telegram message.

    Returns keys:
        unit, qty_plan, price_plan, price_deviation_pct, over_plan,
        stock_now, active_projects, future_projects.
    """
    out: Dict[str, Any] = {
        "unit": "",
        "qty_plan": None,
        "price_plan": None,
        "price_deviation_pct": None,
        "over_plan": False,
        "stock_now": None,
        "active_projects": None,
        "future_projects": None,
    }

    try:
        all_lists = await lists.get_lists(client, project_id)
        target = lists.find_list_by_keyword(all_lists, "материал")
        if target:
            list_id = int(target["ID"])
            iblock_code = target.get("IBLOCK_CODE", "")
            fields_resp = await lists.get_fields(client, list_id, iblock_code, project_id)
            field_map = lists.resolve_field_map(fields_resp)
            elements = await lists.get_elements(client, list_id, iblock_code, project_id)
            elem = lists.find_element_by_name(elements, material_name)
            if elem:
                pid_unit = next(
                    (pid for n, pid in field_map.items()
                     if any(kw in n.lower() for kw in ["ед.", "единиц", "ед.изм", "unit"])),
                    None,
                )
                pid_qty_plan = lists._resolve_filter_pid(field_map, "объём план")
                pid_price_plan = next(
                    (pid for n, pid in field_map.items() if "цена ед" in n.lower() and "план" in n.lower()),
                    None,
                )
                pid_stock = lists._resolve_filter_pid(field_map, "остаток")
                pid_bought = next(
                    (pid for n, pid in field_map.items() if "куплено" in n.lower() and "объём" in n.lower()),
                    None,
                )
                if pid_unit:
                    out["unit"] = lists.get_prop_value_str(elem, pid_unit) or ""
                if pid_qty_plan:
                    qty_plan = float(lists.get_prop_value(elem, pid_qty_plan) or 0)
                    out["qty_plan"] = qty_plan
                    bought_cur = float(lists.get_prop_value(elem, pid_bought) or 0) if pid_bought else 0.0
                    if qty_plan > 0 and (bought_cur + qty) > qty_plan:
                        out["over_plan"] = True
                if pid_price_plan:
                    price_plan = float(lists.get_prop_value(elem, pid_price_plan) or 0)
                    out["price_plan"] = price_plan
                    if price_plan > 0:
                        out["price_deviation_pct"] = round((price - price_plan) / price_plan * 100.0, 1)
                if pid_stock:
                    out["stock_now"] = float(lists.get_prop_value(elem, pid_stock) or 0)
    except Exception as e:
        logger.warning(f"material_context: project {project_id} read failed: {e}")

    try:
        usage = await _fetch_material_usage(client, material_name)
        out["active_projects"] = usage["active_projects"]
        out["future_projects"] = usage["future_projects"]
    except Exception as e:
        logger.warning(f"material_context: cross-project usage failed: {e}")

    return out


# ---------------------------------------------------------------------------
# Buyer-purchase apply (extracted from legacy /api/buyer-report)
# ---------------------------------------------------------------------------


async def _apply_buyer_purchase(
    client: BitrixClient,
    project_id: int,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Update "3. Материалы" with Объём куплено / Остаток / weighted Цена ед. факт.

    ``items``: list of dicts with at least ``material_name``, ``qty``, ``price``.
    Returns: ``{"updated": [...names], "errors": [...], "warnings": [...], "cascade_pairs": set}``.
    """
    from utils.cascade import cascade_update_task, cascade_update_budget  # local import to avoid cycle

    all_lists = await lists.get_lists(client, project_id)
    target = lists.find_list_by_keyword(all_lists, "материал")
    if not target:
        return {"updated": [], "errors": ["Materials list not found"], "warnings": [], "cascade_pairs": set()}

    list_id = int(target["ID"])
    iblock_code = target.get("IBLOCK_CODE", "")
    fields_resp = await lists.get_fields(client, list_id, iblock_code, project_id)
    field_map = lists.resolve_field_map(fields_resp)
    elements = await lists.get_elements(client, list_id, iblock_code, project_id)

    pid_qty_bought = next(
        (pid for fname, pid in field_map.items() if "куплено" in fname.lower() and "объём" in fname.lower()),
        None,
    )
    pid_qty_plan = next(
        (pid for fname, pid in field_map.items() if "объём план" in fname.lower()),
        None,
    )
    pid_stock = next((pid for fname, pid in field_map.items() if "остаток" in fname.lower()), None)
    pid_price_fact = next(
        (pid for fname, pid in field_map.items() if "цена ед" in fname.lower() and "факт" in fname.lower()),
        None,
    )
    pid_etap = lists._resolve_filter_pid(field_map, "этап")
    pid_zadacha = lists._resolve_filter_pid(field_map, "задача")

    updated: List[str] = []
    errors: List[str] = []
    warnings: List[str] = []
    cascade_pairs: set[tuple[str, str]] = set()

    for item in items:
        mat_name = (item.get("material_name") or "").strip()
        qty_bought = float(item.get("qty") or item.get("qty_bought") or 0)
        unit_price = float(item.get("price") or 0)
        total_cost = float(item.get("total") or (qty_bought * unit_price))
        if not mat_name:
            continue

        elem = lists.find_element_by_name(elements, mat_name)
        if not elem:
            errors.append(f"Material not found: {mat_name}")
            continue

        element_id = int(elem["ID"])

        if pid_etap and pid_zadacha:
            etap_val = lists.get_prop_value_str(elem, pid_etap)
            zadacha_val = lists.get_prop_value_str(elem, pid_zadacha)
            if etap_val and zadacha_val:
                cascade_pairs.add((etap_val, zadacha_val))

        if pid_qty_plan and qty_bought > 0:
            qty_plan_val = float(lists.get_prop_value(elem, pid_qty_plan) or 0)
            qty_bought_cur = float(lists.get_prop_value(elem, pid_qty_bought) or 0) if pid_qty_bought else 0.0
            new_total_bought = qty_bought_cur + qty_bought
            if qty_plan_val > 0 and new_total_bought > qty_plan_val:
                over = round(new_total_bought - qty_plan_val, 3)
                warnings.append(f"{mat_name}: превышение плана на {over} ед.")

        merged = lists.extract_all_prop_values(elem)

        if pid_price_fact and pid_qty_bought and total_cost > 0:
            prev_qty = lists.get_prop_value(elem, pid_qty_bought) or 0.0
            prev_price = lists.get_prop_value(elem, pid_price_fact) or 0.0
            prev_cost = prev_qty * prev_price
            new_total_qty = prev_qty + qty_bought
            new_total_cost = prev_cost + total_cost
            if new_total_qty > 0:
                merged[pid_price_fact] = round(new_total_cost / new_total_qty, 2)

        if pid_qty_bought:
            cur = lists.get_prop_value(elem, pid_qty_bought) or 0.0
            merged[pid_qty_bought] = cur + qty_bought

        if pid_stock:
            cur = lists.get_prop_value(elem, pid_stock) or 0.0
            merged[pid_stock] = cur + qty_bought

        await lists.update_element(client, list_id, iblock_code, project_id, element_id, merged, name=mat_name)
        updated.append(mat_name)
        logger.info(f"Approved purchase applied: '{mat_name}' qty+={qty_bought} project {project_id}")

    if cascade_pairs:
        try:
            unique_etaps: set[str] = set()
            for etap_val, zadacha_val in cascade_pairs:
                await cascade_update_task(client, project_id, etap_val, zadacha_val)
                unique_etaps.add(etap_val)
            for etap_val in unique_etaps:
                await cascade_update_budget(client, project_id, etap_val)
        except Exception as cascade_err:
            logger.error(f"Cascade after approval failed for project {project_id}: {cascade_err}", exc_info=True)

    return {"updated": updated, "errors": errors, "warnings": warnings, "cascade_pairs": cascade_pairs}


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _append_history(history: List[Dict[str, Any]], entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    history = list(history or [])
    history.append({"ts": _now_iso(), **entry})
    return history


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_request(
    client: BitrixClient,
    project_id: int,
    project_name: str,
    items: List[Dict[str, Any]],
    file_name: Optional[str],
    file_bytes: Optional[bytes],
    author: str,
    etap: str = "",
    zadacha: str = "",
    buyer_comment: str = "",
) -> Dict[str, Any]:
    """
    Create a new purchase request: upload file, insert list row, create audit task,
    send Telegram message. Returns ``{"request_id", "task_id", "context"}``.

    ``buyer_comment`` is the buyer's justification (required when the buyer's price
    exceeds the planned price); it is stored on ``f_pr_comment`` and shown to the
    approver.
    """
    from app.notifications.telegram import send_telegram_with_buttons

    # --- upload file (best effort — request still works without an attachment)
    file_url = ""
    file_disk_id: Optional[int] = None
    if file_name and file_bytes:
        try:
            uploaded = await disk_methods.upload_file_to_workgroup(
                client, project_id, DISK_FOLDER_NAME, file_name, file_bytes,
            )
            file_disk_id = int(uploaded.get("ID") or 0) or None
            file_url = uploaded.get("DOWNLOAD_URL") or uploaded.get("DETAIL_URL") or ""
        except Exception as e:
            logger.warning(f"Disk upload failed for project {project_id}: {e}")

    # --- ensure list exists, fetch existing rows for № assignment
    list_info = await lists.get_or_create_purchase_requests_list(client, project_id)
    list_id = int(list_info["list_id"])
    iblock_code = list_info["iblock_code"]
    field_ids: Dict[str, int] = list_info["field_ids"]

    existing = await lists.get_elements(client, list_id, iblock_code, project_id)
    request_no = _next_request_no(existing, field_ids.get("f_pr_no"))

    # --- compute material context for the first item (used in TG/page summary)
    primary_item = items[0] if items else {"material_name": "", "qty": 0, "price": 0}
    ctx = await material_context(
        client, project_id, primary_item.get("material_name", ""),
        float(primary_item.get("qty") or 0), float(primary_item.get("price") or 0),
    )
    if not primary_item.get("unit") and ctx.get("unit"):
        for it in items:
            if not it.get("unit"):
                it["unit"] = ctx["unit"]

    total_sum = _items_total(items)

    # --- insert the list row (status = pending)
    history = _append_history([], {"event": "created", "actor": author, "source": "form"})
    field_values: Dict[int, Any] = {}

    def _set(code: str, value: Any) -> None:
        pid = field_ids.get(code)
        if pid and value is not None and value != "":
            field_values[pid] = value

    _set("f_pr_no", request_no)
    _set("f_pr_date", datetime.now().date().isoformat())
    _set("f_pr_author", author)
    _set("f_pr_etap", etap)
    _set("f_pr_zadacha", zadacha)
    _set("f_pr_material", json.dumps(items, ensure_ascii=False))
    if len(items) == 1:
        _set("f_pr_qty", items[0].get("qty"))
        _set("f_pr_unit", items[0].get("unit") or ctx.get("unit"))
        _set("f_pr_price", items[0].get("price"))
        _set("f_pr_total", items[0].get("total") or (float(items[0].get("qty") or 0) * float(items[0].get("price") or 0)))
    else:
        _set("f_pr_total", total_sum)
    _set("f_pr_file_url", file_url)
    _set("f_pr_status", STATUS_PENDING)
    _set("f_pr_history", json.dumps(history, ensure_ascii=False))
    if buyer_comment:
        _set("f_pr_comment", f"[{author}] {buyer_comment}")

    row_name = f"Заявка №{request_no}: {primary_item.get('material_name', '')}".strip()
    request_id = await lists.add_element(
        client, list_id, iblock_code, project_id,
        element_code=f"pr_{int(time.time())}_{request_no}",
        name=row_name,
        field_values=field_values,
    )
    request_id = int(request_id)

    # --- build approval URL now that we have request_id
    page_url = approval_url(request_id)

    # --- create audit task in Bitrix
    items_block = "\n".join(
        f"• {it.get('material_name', '')}: {it.get('qty')} {it.get('unit', ctx.get('unit') or '')} × "
        f"{it.get('price')} ₽ = {it.get('total') or float(it.get('qty') or 0) * float(it.get('price') or 0):.2f} ₽"
        for it in items
    )
    description = (
        f"[B]Заявка на закупку №{request_no}[/B] (проект: {project_name})\n"
        f"Автор: {author}\n"
        f"Этап: {etap or '—'} / Задача: {zadacha or '—'}\n"
        f"\n[B]Позиции:[/B]\n{items_block}\n\n"
        f"[B]Открыть форму согласования:[/B]\n{page_url}\n"
    )
    if buyer_comment:
        description += f"\n[B]Комментарий закупщика:[/B] {buyer_comment}\n"
    if file_url:
        description += f"\n[B]Документ поставщика:[/B] {file_url}\n"

    uf_fields: Dict[str, Any] = {}
    if file_disk_id:
        uf_fields["UF_TASK_WEBDAV_FILES"] = disk_methods.task_webdav_files_value([file_disk_id])

    task_id = 0
    try:
        task_id = await tasks_methods.create_task(
            client,
            title=f"Заявка на закупку №{request_no} — {primary_item.get('material_name', '')}",
            responsible_id=settings.purchase_approver_user_id,
            description=description,
            group_id=project_id,
            uf_fields=uf_fields or None,
        )
    except Exception as e:
        logger.error(f"Audit task creation failed for request {request_id}: {e}")

    if task_id and field_ids.get("f_pr_btask_id"):
        try:
            elem_after = await lists.get_elements(client, list_id, iblock_code, project_id)
            row = next((r for r in elem_after if int(r["ID"]) == request_id), None)
            if row:
                merged = lists.extract_all_prop_values(row)
                merged[field_ids["f_pr_btask_id"]] = task_id
                await lists.update_element(
                    client, list_id, iblock_code, project_id, request_id, merged, name=row_name,
                )
        except Exception as e:
            logger.warning(f"Failed to write Bitrix task ID back to request {request_id}: {e}")

    # --- send Telegram with rich body + inline keyboard
    try:
        msg = _format_telegram_body(
            request_no=request_no, project_name=project_name, author=author,
            etap=etap, zadacha=zadacha, items=items, total_sum=total_sum,
            ctx=ctx, file_url=file_url, buyer_comment=buyer_comment,
        )
        keyboard = [
            [
                {"text": "✅ Подтвердить", "callback_data": f"pr:approve:{request_id}"},
                {"text": "❌ Отклонить", "callback_data": f"pr:reject:{request_id}"},
            ],
            [
                {"text": "📝 Открыть форму", "url": page_url},
                {"text": "💬 Написать", "callback_data": f"pr:comment:{request_id}"},
            ],
        ]
        await send_telegram_with_buttons(msg, keyboard)
    except Exception as e:
        logger.warning(f"Telegram notification failed for request {request_id}: {e}")

    return {
        "request_id": request_id,
        "request_no": request_no,
        "task_id": task_id,
        "context": ctx,
    }


def _format_telegram_body(
    *,
    request_no: int,
    project_name: str,
    author: str,
    etap: str,
    zadacha: str,
    items: List[Dict[str, Any]],
    total_sum: float,
    ctx: Dict[str, Any],
    file_url: str,
    buyer_comment: str = "",
) -> str:
    """Build the rich HTML body for the approver's Telegram message."""
    def esc(s: Any) -> str:
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines: List[str] = []
    lines.append(f"🛒 <b>Заявка на закупку №{request_no}</b>")
    lines.append(f"🏗 Проект: {esc(project_name)}")
    lines.append(f"👤 Автор: {esc(author)}")
    if etap or zadacha:
        lines.append(f"📋 Этап: {esc(etap or '—')} / Задача: {esc(zadacha or '—')}")
    lines.append("")
    lines.append("<b>Позиции:</b>")
    for it in items:
        qty = float(it.get("qty") or 0)
        price = float(it.get("price") or 0)
        unit = it.get("unit") or ctx.get("unit") or ""
        total = float(it.get("total") or (qty * price))
        lines.append(f"• {esc(it.get('material_name', ''))}: {qty} {esc(unit)} × {price} ₽ = {total:.2f} ₽")
    lines.append(f"<b>Итого:</b> {total_sum:.2f} ₽")
    lines.append("")

    price_plan = ctx.get("price_plan")
    if price_plan and items:
        first = items[0]
        sev = format_price_deviation(
            float(first.get("price") or 0),
            float(price_plan or 0),
            float(first.get("qty") or 0),
        )
        if sev["severity"] not in ("none",):
            if sev["header"]:
                lines.append(f"{sev['emoji']} <b>{sev['header']}</b>")
                lines.append(sev["body"])
            else:
                lines.append(f"{sev['emoji']} {sev['body']}")
    if ctx.get("over_plan"):
        lines.append("⚠ Объём превышает план для этого материала")
    if ctx.get("stock_now") is not None:
        lines.append(f"📦 Остаток на складе сейчас: {ctx['stock_now']}")
    if ctx.get("active_projects") is not None:
        lines.append(f"🏗 Активных проектов с этим материалом: {ctx['active_projects']}")
    if ctx.get("future_projects") is not None:
        lines.append(f"🗓 Запланировано в будущих проектах: {ctx['future_projects']}")

    if buyer_comment:
        lines.append("")
        lines.append(f"💬 <b>Комментарий закупщика:</b> {esc(buyer_comment)}")

    if file_url:
        lines.append("")
        lines.append(f'📎 <a href="{esc(file_url)}">Коммерческое предложение</a>')

    return "\n".join(lines)


async def _load_request(
    client: BitrixClient, project_id: int, request_id: int,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Load list-info + the row dict for ``request_id``. Raises ValueError if not found."""
    list_info = await lists.get_or_create_purchase_requests_list(client, project_id)
    list_id = int(list_info["list_id"])
    iblock_code = list_info["iblock_code"]
    elements = await lists.get_elements(client, list_id, iblock_code, project_id)
    row = next((r for r in elements if int(r["ID"]) == request_id), None)
    if not row:
        raise ValueError(f"Purchase request {request_id} not found in project {project_id}")
    return list_info, row, _row_to_request(row, list_info["field_ids"])


async def list_pending_across_projects(
    client: BitrixClient,
) -> List[Dict[str, Any]]:
    """
    Walk all projects and return every purchase request whose status is PENDING,
    flattened for the Bitrix-widget approver view.
    """
    out: List[Dict[str, Any]] = []
    try:
        projects = await workgroups.list_projects(client)
    except Exception as e:
        logger.warning(f"list_pending_across_projects: list_projects failed: {e}")
        return out

    for proj in projects:
        gid = int(proj["id"])
        proj_name = proj.get("name", f"Проект #{gid}")
        try:
            list_info = await lists.get_or_create_purchase_requests_list(client, gid)
            list_id = int(list_info["list_id"])
            iblock_code = list_info["iblock_code"]
            elements = await lists.get_elements(client, list_id, iblock_code, gid)
        except Exception as e:
            logger.debug(f"list_pending: project {gid} skipped: {e}")
            continue

        for raw in elements:
            req = _row_to_request(raw, list_info["field_ids"])
            if req["status"] != STATUS_PENDING:
                continue
            primary = req["items"][0] if req["items"] else {}
            out.append({
                "project_id": gid,
                "project_name": proj_name,
                "request_id": req["id"],
                "request_no": req["no"],
                "date": req["date"],
                "author": req["author"],
                "material": primary.get("material_name", ""),
                "qty": float(primary.get("qty") or 0),
                "unit": primary.get("unit") or "",
                "total_sum": _items_total(req["items"]),
                "file_url": req["file_url"],
            })
    out.sort(key=lambda r: (r["date"] or "", r["request_no"]), reverse=True)
    return out


async def find_request_in_any_project(
    client: BitrixClient, request_id: int,
) -> Optional[Tuple[int, Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
    """
    Telegram callbacks know request_id but not project_id. Walk projects to locate it.

    Returns ``(project_id, list_info, raw_row, decoded_row)`` or ``None``.
    """
    projects = await workgroups.list_projects(client)
    for proj in projects:
        gid = int(proj["id"])
        try:
            list_info = await lists.get_or_create_purchase_requests_list(client, gid)
            list_id = int(list_info["list_id"])
            elements = await lists.get_elements(client, list_id, list_info["iblock_code"], gid)
            row = next((r for r in elements if int(r["ID"]) == request_id), None)
            if row:
                return gid, list_info, row, _row_to_request(row, list_info["field_ids"])
        except Exception as e:
            logger.debug(f"find_request_in_any_project: project {gid} skipped: {e}")
    return None


async def resolve_request(
    client: BitrixClient,
    project_id: int,
    request_id: int,
    decision: str,
    actor: str,
    source: str,
    comment: str = "",
) -> Dict[str, Any]:
    """
    Apply ``decision`` to a request. Idempotent — if the request is already
    resolved, returns the existing state without mutating.

    ``decision`` is one of ``DECISION_APPROVE``, ``DECISION_REJECT``, ``DECISION_COMMENT``.
    """
    from app.notifications.telegram import send_telegram

    list_info, row, request = await _load_request(client, project_id, request_id)
    field_ids: Dict[str, int] = list_info["field_ids"]

    if decision != DECISION_COMMENT and request["status"] != STATUS_PENDING:
        logger.info(
            f"Request {request_id} already resolved as '{request['status']}', "
            f"ignoring {decision} from {source}"
        )
        return {"already_resolved": True, "status": request["status"], "request": request}

    history = _append_history(request["history"], {
        "event": decision,
        "actor": actor,
        "source": source,
        "comment": comment or None,
    })

    apply_result: Optional[Dict[str, Any]] = None
    if decision == DECISION_APPROVE:
        apply_result = await _apply_buyer_purchase(client, project_id, request["items"])
        new_status = STATUS_APPROVED
    elif decision == DECISION_REJECT:
        new_status = STATUS_REJECTED
    elif decision == DECISION_COMMENT:
        new_status = request["status"]
    else:
        raise ValueError(f"Unknown decision: {decision}")

    merged = lists.extract_all_prop_values(row)
    if field_ids.get("f_pr_status"):
        merged[field_ids["f_pr_status"]] = new_status
    if field_ids.get("f_pr_history"):
        merged[field_ids["f_pr_history"]] = json.dumps(history, ensure_ascii=False)
    if comment and field_ids.get("f_pr_comment"):
        prev = request["comment"]
        merged[field_ids["f_pr_comment"]] = (prev + "\n" if prev else "") + f"[{actor}] {comment}"

    await lists.update_element(
        client, int(list_info["list_id"]), list_info["iblock_code"], project_id,
        request_id, merged, name=row.get("NAME"),
    )

    # Mirror to Bitrix task (audit) and Telegram (ack).
    if request["bitrix_task_id"]:
        try:
            tag = {DECISION_APPROVE: "✅ Подтверждено", DECISION_REJECT: "❌ Отклонено", DECISION_COMMENT: "💬 Комментарий"}[decision]
            tag_msg = f"{tag} ({source}) — {actor}"
            if comment:
                tag_msg += f"\n{comment}"
            await tasks_methods.add_task_comment(client, request["bitrix_task_id"], tag_msg)
        except Exception as e:
            logger.warning(f"Audit task comment failed for request {request_id}: {e}")

        # Approve OR reject closes the audit task; "comment" leaves it open.
        if decision in (DECISION_APPROVE, DECISION_REJECT):
            try:
                await tasks_methods.complete_task(client, request["bitrix_task_id"])
            except Exception as e:
                logger.warning(f"Audit task complete failed for request {request_id}: {e}")

    try:
        ack_lines = [f"<b>Заявка №{request['no']}</b>"]
        if decision == DECISION_APPROVE:
            ack_lines.append(f"✅ Подтверждено — {actor} ({source})")
            if apply_result:
                names = ", ".join(apply_result.get("updated", [])) or "—"
                ack_lines.append(f"Обновлено в материалах: {names}")
                for w in apply_result.get("warnings", []):
                    ack_lines.append(f"⚠ {w}")
        elif decision == DECISION_REJECT:
            ack_lines.append(f"❌ Отклонено — {actor} ({source})")
        else:
            ack_lines.append(f"💬 {actor} написал ({source}): {comment}")
        await send_telegram("\n".join(ack_lines))
    except Exception as e:
        logger.warning(f"Telegram ack failed for request {request_id}: {e}")

    refreshed = dict(request)
    refreshed["status"] = new_status
    refreshed["history"] = history
    if comment:
        refreshed["comment"] = (request["comment"] + "\n" if request["comment"] else "") + f"[{actor}] {comment}"

    return {
        "already_resolved": False,
        "status": new_status,
        "request": refreshed,
        "apply_result": apply_result,
    }
