"""
Daily morning digest for BuildControl.

Scheduled to run at 09:00 Moscow time. Pulls all yesterday's activity
across all active projects and sends a structured summary to Telegram.

Includes:
- Task progress changes
- Foreman reports (materials, labor, comments)
- Purchase activity
- Schedule slippage warnings
- No-report alerts
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from bitrix.client import BitrixClient
from bitrix.methods import lists, workgroups
from app.notifications.alerts import (
    _get_list_context,
    _find_pid,
    _parse_date,
    _esc,
)
from app.notifications.telegram import send_telegram

logger = logging.getLogger(__name__)


async def send_morning_digest() -> None:
    """
    Build and send the daily morning digest for all active projects.
    Called by APScheduler at 09:00 Moscow time.
    """
    logger.info("Morning digest: starting...")

    try:
        async with BitrixClient() as client:
            projects = await workgroups.list_projects(client)

        if not projects:
            logger.info("Morning digest: no active projects found")
            return

        yesterday = date.today() - timedelta(days=1)
        digest_parts: list[str] = []
        projects_with_reports: set[int] = set()

        for proj in projects:
            project_id = int(proj["id"])
            project_name = proj.get("name", f"Проект #{project_id}")

            try:
                async with BitrixClient() as client:
                    section = await _build_project_section(
                        client, project_id, project_name, yesterday,
                    )
                if section:
                    digest_parts.append(section["text"])
                    if section["has_reports"]:
                        projects_with_reports.add(project_id)
            except Exception as e:
                logger.error(f"Morning digest: failed for project {project_id}: {e}")
                digest_parts.append(
                    f"\n<b>{_esc(project_name)}</b>\n"
                    f"  Ошибка при сборе данных"
                )

        # No-report warnings
        no_report_projects = [
            p for p in projects
            if int(p["id"]) not in projects_with_reports
        ]
        if no_report_projects:
            names = "\n".join(
                f"  • {_esc(p.get('name', '?'))}"
                for p in no_report_projects
            )
            digest_parts.append(
                f"\n🔕 <b>Без отчётов вчера:</b>\n{names}"
            )

        if not digest_parts:
            logger.info("Morning digest: nothing to report")
            return

        header = f"☀️ <b>Утренний дайджест — {yesterday.strftime('%d.%m.%Y')}</b>\n"
        full_message = header + "\n".join(digest_parts)

        await send_telegram(full_message)
        logger.info("Morning digest: sent successfully")

    except Exception as e:
        logger.error(f"Morning digest failed: {e}", exc_info=True)


async def _build_project_section(
    client: BitrixClient,
    project_id: int,
    project_name: str,
    target_date: date,
) -> Optional[Dict[str, Any]]:
    """
    Build a digest section for one project.

    Returns {"text": str, "has_reports": bool} or None if no activity.
    """
    lines: list[str] = []
    has_reports = False

    # --- 1. Foreman reports from yesterday ---
    report_lines = await _get_yesterday_reports(client, project_id, target_date)
    if report_lines:
        has_reports = True
        lines.extend(report_lines)

    # --- 2. Task progress / schedule slippage ---
    task_lines = await _get_task_status(client, project_id)
    if task_lines:
        lines.extend(task_lines)

    if not lines:
        return None

    section_header = f"\n🏗 <b>{_esc(project_name)}</b>\n{'━' * 20}\n"
    return {
        "text": section_header + "\n".join(lines),
        "has_reports": has_reports,
    }


async def _get_yesterday_reports(
    client: BitrixClient,
    project_id: int,
    target_date: date,
) -> list[str]:
    """Pull foreman reports submitted on target_date."""
    lines: list[str] = []

    ctx = await _get_list_context(client, project_id, "отчет")
    if not ctx:
        return lines

    _, _, field_map, elements = ctx

    pid_date = _find_pid(field_map, "дата")
    pid_comment = _find_pid(field_map, "комментар")
    pid_materials = _find_pid(field_map, "материал")
    pid_labor = _find_pid(field_map, "трудозатрат")

    target_str = target_date.isoformat()

    for elem in elements:
        report_date_raw = lists.get_prop_value_str(elem, pid_date) if pid_date else None
        if not report_date_raw:
            continue
        report_dt = _parse_date(report_date_raw)
        if not report_dt or report_dt != target_date:
            continue

        report_name = elem.get("NAME", "Отчет")
        lines.append(f"\n📋 <b>Отчёт:</b> {_esc(report_name)}")

        # Comment
        if pid_comment:
            comment = lists.get_prop_value_str(elem, pid_comment)
            if comment:
                lines.append(f"  Комментарий: {_esc(comment[:200])}")

        # Materials
        if pid_materials:
            mat_raw = lists.get_prop_value_str(elem, pid_materials)
            if mat_raw:
                try:
                    mat_list = json.loads(mat_raw)
                    for m in mat_list:
                        name = m.get("name", "?")
                        qty = m.get("quantity", 0)
                        lines.append(f"  • Материал: {_esc(name)} — {qty}")
                except (json.JSONDecodeError, TypeError):
                    pass

        # Labor
        if pid_labor:
            lab_raw = lists.get_prop_value_str(elem, pid_labor)
            if lab_raw:
                try:
                    lab_list = json.loads(lab_raw)
                    for w in lab_list:
                        name = w.get("worker_name", "?")
                        hours = w.get("hours", 0)
                        lines.append(f"  • Трудозатраты: {_esc(name)} — {hours} ч")
                except (json.JSONDecodeError, TypeError):
                    pass

    return lines


async def _get_task_status(
    client: BitrixClient,
    project_id: int,
) -> list[str]:
    """Get task completion status and schedule slippage warnings."""
    lines: list[str] = []

    ctx = await _get_list_context(client, project_id, "задач")
    if not ctx:
        return lines

    _, _, field_map, elements = ctx

    pid_etap = lists._resolve_filter_pid(field_map, "этап")
    pid_pct = lists._resolve_filter_pid(field_map, "готовн. факт")
    if not pid_pct:
        pid_pct = lists._resolve_filter_pid(field_map, "готовн факт")
    pid_budget_plan = lists._resolve_filter_pid(field_map, "бюджет план")
    pid_budget_fact = lists._resolve_filter_pid(field_map, "бюджет факт")
    pid_start_plan = _find_pid(field_map, "нач. план")
    if not pid_start_plan:
        pid_start_plan = _find_pid(field_map, "нач план")
    pid_end_plan = _find_pid(field_map, "ок. план")
    if not pid_end_plan:
        pid_end_plan = _find_pid(field_map, "ок план")

    slippage_warnings: list[str] = []
    budget_warnings: list[str] = []

    today = date.today()

    for elem in elements:
        task_name = elem.get("NAME", "?")
        etap = lists.get_prop_value_str(elem, pid_etap) if pid_etap else ""
        pct = float(lists.get_prop_value(elem, pid_pct) or 0) if pid_pct else 0.0

        # Schedule slippage check
        if pid_start_plan and pid_end_plan:
            start_raw = lists.get_prop_value_str(elem, pid_start_plan)
            end_raw = lists.get_prop_value_str(elem, pid_end_plan)
            if start_raw and end_raw:
                start_dt = _parse_date(start_raw)
                end_dt = _parse_date(end_raw)
                if start_dt and end_dt and today >= start_dt:
                    total_days = (end_dt - start_dt).days
                    if total_days > 0:
                        elapsed = (today - start_dt).days
                        expected_pct = min(100.0, elapsed / total_days * 100.0)
                        gap = expected_pct - pct
                        if gap >= 20.0:
                            slippage_warnings.append(
                                f"  ⚠ {_esc(task_name)}: готовность {pct:.0f}%, "
                                f"ожидалось {expected_pct:.0f}% (отставание {gap:.0f} п.п.)"
                            )

        # Budget threshold check
        if pid_budget_plan and pid_budget_fact:
            bp = float(lists.get_prop_value(elem, pid_budget_plan) or 0)
            bf = float(lists.get_prop_value(elem, pid_budget_fact) or 0)
            if bp > 0:
                budget_ratio = bf / bp
                if budget_ratio >= 0.80 and pct < 70.0:
                    budget_warnings.append(
                        f"  ⚠ {_esc(task_name)}: бюджет {budget_ratio * 100:.0f}%, "
                        f"готовность {pct:.0f}%"
                    )

    if slippage_warnings:
        lines.append("\n⏰ <b>Отставание от графика:</b>")
        lines.extend(slippage_warnings)

    if budget_warnings:
        lines.append("\n🔴 <b>Перерасход бюджета:</b>")
        lines.extend(budget_warnings)

    return lines
