"""
Event-driven alert checks for BuildControl.

Each function checks a condition and sends a Telegram alert if triggered.
All calls are fire-and-forget: exceptions are caught internally.

Alert types:
1. Price overrun       — purchase price > plan price
2. Consumption ratio   — cross-task: material consumed faster than work progresses
3. Warehouse balance   — stock below 20% of plan
4. Budget threshold    — budget spent > 80% but task < 70% complete
5. Schedule slippage   — task behind timeline by > 20 percentage points
6. No-report           — active project with no report for 2+ days (used in digest)
7. Daily digest        — handled in digest.py
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from bitrix.client import BitrixClient
from bitrix.methods import lists
from app.notifications.telegram import send_telegram

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Purchase above plan price
# ---------------------------------------------------------------------------

async def check_price_overrun(
    project_name: str,
    material_name: str,
    price_plan: float,
    price_fact: float,
    qty_bought: float,
    unit: str = "ед.",
) -> None:
    """Alert if actual purchase price exceeds planned price."""
    try:
        if price_plan <= 0 or price_fact <= price_plan:
            return

        overpay_pct = round((price_fact - price_plan) / price_plan * 100, 1)
        overpay_total = round((price_fact - price_plan) * qty_bought, 2)

        msg = (
            f"💸 <b>Превышение закупочной цены</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏗 Проект: {_esc(project_name)}\n"
            f"📦 Материал: {_esc(material_name)}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Цена план:  {price_plan:,.2f} ₽/{unit}\n"
            f"💰 Цена факт:  {price_fact:,.2f} ₽/{unit}\n"
            f"📈 Переплата: +{overpay_pct}% ({overpay_total:,.0f} ₽ на {qty_bought} {unit})"
        )
        await send_telegram(msg)
    except Exception as e:
        logger.error(f"Alert check_price_overrun failed: {e}")


# ---------------------------------------------------------------------------
# 2. Disproportionate consumption (cross-task aggregation)
# ---------------------------------------------------------------------------

async def check_consumption_ratio(
    client: BitrixClient,
    project_id: int,
    project_name: str,
    material_name: str,
    threshold: float = 1.3,
) -> None:
    """
    Cross-task consumption alert.

    Finds ALL rows for this material across the project, computes expected
    consumption based on each linked task's completion %, and compares with
    actual total consumption.

    Alerts if actual > expected × threshold.
    """
    try:
        # Get materials list
        mat_ctx = await _get_list_context(client, project_id, "материал")
        if not mat_ctx:
            return
        _, _, mat_fm, mat_elems = mat_ctx

        # Get tasks list for completion %
        task_ctx = await _get_list_context(client, project_id, "задач")
        if not task_ctx:
            return
        _, _, task_fm, task_elems = task_ctx

        pid_qty_plan = _find_pid(mat_fm, "объём план")
        pid_qty_spent = _find_pid(mat_fm, "израсходовано")
        pid_etap = lists._resolve_filter_pid(mat_fm, "этап")
        pid_zadacha = lists._resolve_filter_pid(mat_fm, "задача")
        pid_task_pct = lists._resolve_filter_pid(task_fm, "готовн. факт")
        if not pid_task_pct:
            pid_task_pct = lists._resolve_filter_pid(task_fm, "готовн факт")

        if not pid_qty_plan or not pid_qty_spent:
            return

        # Find all material rows matching this name
        matching_rows = [
            e for e in mat_elems
            if (e.get("NAME") or "").strip().lower() == material_name.strip().lower()
        ]
        if not matching_rows:
            return

        total_plan = 0.0
        total_consumed = 0.0
        expected_consumption = 0.0
        task_details: list[str] = []

        for row in matching_rows:
            qty_plan = float(lists.get_prop_value(row, pid_qty_plan) or 0)
            qty_consumed = float(lists.get_prop_value(row, pid_qty_spent) or 0)
            total_plan += qty_plan
            total_consumed += qty_consumed

            # Get this row's task completion %
            etap_val = lists.get_prop_value_str(row, pid_etap) if pid_etap else None
            zadacha_val = lists.get_prop_value_str(row, pid_zadacha) if pid_zadacha else None

            task_pct = 0.0
            if etap_val and zadacha_val and pid_task_pct:
                matched_tasks = lists.find_elements_by_properties(
                    task_elems, task_fm,
                    {"Этап": etap_val, "Задача": zadacha_val},
                )
                if matched_tasks:
                    task_pct = float(lists.get_prop_value(matched_tasks[0], pid_task_pct) or 0)

            expected_consumption += qty_plan * (task_pct / 100.0)
            task_details.append(
                f"  • {zadacha_val or '?'}: план {qty_plan}, расход {qty_consumed}, "
                f"готовность {task_pct:.0f}%"
            )

        # Avoid division by zero: if expected is 0 but consumed > 0, that's also a flag
        if expected_consumption <= 0:
            if total_consumed > 0 and total_plan > 0:
                # Work hasn't started but material is being consumed
                ratio_text = "∞ (работа не начата, а материал расходуется)"
            else:
                return
        else:
            ratio = total_consumed / expected_consumption
            if ratio < threshold:
                return
            ratio_text = f"{ratio:.1f}×"

        details_str = "\n".join(task_details)
        msg = (
            f"⚠️ <b>Перерасход материала</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏗 Проект: {_esc(project_name)}\n"
            f"📦 Материал: {_esc(material_name)}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📋 План всего:              {total_plan:,.1f}\n"
            f"🔥 Израсходовано:           {total_consumed:,.1f}\n"
            f"🎯 Ожидаемый расход:        {expected_consumption:,.1f}\n"
            f"📊 Превышение:              {ratio_text}\n\n"
            f"По задачам:\n{details_str}"
        )
        await send_telegram(msg)
    except Exception as e:
        logger.error(f"Alert check_consumption_ratio failed: {e}")


# ---------------------------------------------------------------------------
# 3. Warehouse balance
# ---------------------------------------------------------------------------

async def check_warehouse_balance(
    project_name: str,
    material_name: str,
    stock: float,
    qty_plan: float,
    qty_bought: float,
    unit: str = "ед.",
    threshold_pct: float = 0.20,
) -> None:
    """Alert when stock drops below threshold % of planned volume."""
    try:
        if qty_plan <= 0:
            return

        stock_ratio = stock / qty_plan
        if stock_ratio >= threshold_pct:
            return

        # Branching: all planned bought vs more to buy
        if qty_bought >= qty_plan:
            purchase_note = "Весь плановый объём уже закуплен."
        else:
            remaining_to_buy = qty_plan - qty_bought
            purchase_note = (
                f"По плану нужно докупить ещё {remaining_to_buy:,.1f} {unit}."
            )

        msg = (
            f"📉 <b>Низкий остаток на складе</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏗 Проект: {_esc(project_name)}\n"
            f"📦 Материал: {_esc(material_name)}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🗄 Остаток:  {stock:,.1f} {unit} ({stock_ratio * 100:.0f}% от плана)\n"
            f"📋 План:     {qty_plan:,.1f} {unit}\n"
            f"🛒 Куплено:  {qty_bought:,.1f} {unit}\n"
            f"{purchase_note}"
        )
        await send_telegram(msg)
    except Exception as e:
        logger.error(f"Alert check_warehouse_balance failed: {e}")


# ---------------------------------------------------------------------------
# 4. Budget threshold
# ---------------------------------------------------------------------------

async def check_budget_threshold(
    project_name: str,
    task_name: str,
    etap: str,
    budget_plan: float,
    budget_fact: float,
    completion_pct: float,
    budget_threshold: float = 0.80,
    completion_threshold: float = 0.70,
) -> None:
    """Alert when budget is >80% spent but task is <70% complete."""
    try:
        if budget_plan <= 0:
            return

        budget_ratio = budget_fact / budget_plan
        if budget_ratio < budget_threshold:
            return
        if completion_pct / 100.0 >= completion_threshold:
            return

        msg = (
            f"🔴 <b>Бюджет расходуется быстрее работы</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏗 Проект: {_esc(project_name)}\n"
            f"📌 Этап: {_esc(etap)}\n"
            f"📝 Задача: {_esc(task_name)}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💼 Бюджет план:  {budget_plan:,.0f} ₽\n"
            f"💸 Бюджет факт:  {budget_fact:,.0f} ₽  ({budget_ratio * 100:.0f}%)\n"
            f"🔨 Готовность:   {completion_pct:.0f}%"
        )
        await send_telegram(msg)
    except Exception as e:
        logger.error(f"Alert check_budget_threshold failed: {e}")


# ---------------------------------------------------------------------------
# 5. Schedule slippage
# ---------------------------------------------------------------------------

async def check_schedule_slippage(
    project_name: str,
    task_name: str,
    etap: str,
    start_plan: Optional[str],
    end_plan: Optional[str],
    completion_pct: float,
    gap_threshold_pp: float = 20.0,
) -> None:
    """Alert when expected timeline completion exceeds actual completion by >20pp."""
    try:
        if not start_plan or not end_plan:
            return

        start_dt = _parse_date(start_plan)
        end_dt = _parse_date(end_plan)
        if not start_dt or not end_dt:
            return

        today = date.today()
        if today < start_dt:
            return  # Task hasn't started per plan yet

        total_days = (end_dt - start_dt).days
        if total_days <= 0:
            return

        elapsed_days = (today - start_dt).days
        expected_pct = min(100.0, elapsed_days / total_days * 100.0)
        gap = expected_pct - completion_pct

        if gap < gap_threshold_pp:
            return

        days_behind = int(gap / 100.0 * total_days)
        msg = (
            f"⏰ <b>Отставание от графика</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏗 Проект: {_esc(project_name)}\n"
            f"📌 Этап: {_esc(etap)}\n"
            f"📝 Задача: {_esc(task_name)}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🗓 Даты план:           {start_plan} → {end_plan}\n"
            f"🎯 Ожид. готовность:    {expected_pct:.0f}%\n"
            f"✅ Факт. готовность:    {completion_pct:.0f}%\n"
            f"📉 Отставание:          {gap:.0f} п.п. (~{days_behind} дней)"
        )
        await send_telegram(msg)
    except Exception as e:
        logger.error(f"Alert check_schedule_slippage failed: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_list_context(
    client: BitrixClient,
    project_id: int,
    name_keyword: str,
) -> Optional[tuple]:
    """Find list by keyword, return (list_id, iblock_code, field_map, elements)."""
    all_lists = await lists.get_lists(client, project_id)
    target = lists.find_list_by_keyword(all_lists, name_keyword)
    if target:
        list_id = int(target["ID"])
        iblock_code = target.get("IBLOCK_CODE", "")
        fields_resp = await lists.get_fields(client, list_id, iblock_code, project_id)
        field_map = lists.resolve_field_map(fields_resp)
        elements = await lists.get_elements(client, list_id, iblock_code, project_id)
        return list_id, iblock_code, field_map, elements
    return None


def _find_pid(field_map: Dict[str, int], keyword: str) -> Optional[int]:
    """Find property ID by partial keyword match in field names."""
    for name, pid in field_map.items():
        if keyword.lower() in name.lower():
            return pid
    return None


def _parse_date(val: str) -> Optional[date]:
    """Parse a date string (ISO or common Bitrix formats)."""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _esc(text: str) -> str:
    """Escape HTML special characters for Telegram messages."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
