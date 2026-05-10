"""Foreman report and purchase-request endpoints."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from bitrix.client import BitrixClient
from bitrix.methods import lists, tasks as tasks_methods
from config import settings
from db.database import get_db
from db import repo
from utils.cascade import cascade_update_task, cascade_update_budget
from app.notifications.alerts import (
    check_price_overrun,
    check_consumption_ratio,
    check_warehouse_balance,
    check_budget_threshold,
    check_schedule_slippage,
)
from app.routes.projects import _get_list_context, _filter_task_elements

router = APIRouter(prefix="", tags=["reports"])
logger = logging.getLogger(__name__)


def _compute_completion_pct(stages: list[dict], stage_id: int) -> float:
    """
    Compute % completion based on kanban stage position across ALL stages.
    NEW (first stage) = 0%, FINISH (last stage) = 100%.
    E.g. 3 stages: NEW(0%), In Progress(50%), Done(100%).
    """
    for i, s in enumerate(stages):
        if int(s["ID"]) == stage_id:
            denom = max(len(stages) - 1, 1)
            return round(i / denom * 100, 1)
    return 0.0


def _resolve_stage_system_type(
    stages: list[dict],
    stage_id: int,
) -> Optional[str]:
    """
    Resolve stage SYSTEM_TYPE by stage ID.

    If Bitrix returns null SYSTEM_TYPE for custom stages, use position fallback:
    first=NEW, last=FINISH, middle=PROGRESS.
    """
    for index, stage in enumerate(stages):
        if int(stage["ID"]) != int(stage_id):
            continue
        system_type = stage.get("SYSTEM_TYPE") or None
        if system_type:
            return str(system_type)
        if index == 0:
            return "NEW"
        if index == len(stages) - 1:
            return "FINISH"
        return "PROGRESS"
    return None


def _resolve_parent_stage_targets(stages: list[dict]) -> tuple[Optional[int], Optional[int]]:
    """
    Return (progress_stage_id, finish_stage_id) for parent task auto-move logic.

    - Progress stage: first stage with SYSTEM_TYPE in PROGRESS/WORK/REVIEW;
      if none resolved, fallback to the second stage by SORT.
    - Finish stage: last stage by SORT.
    """
    if not stages:
        return None, None

    progress_stage_id: Optional[int] = None
    finish_stage_id = int(stages[-1]["ID"])

    for index, stage in enumerate(stages):
        stage_id = int(stage["ID"])
        system_type = stage.get("SYSTEM_TYPE") or None
        if not system_type:
            if index == 0:
                system_type = "NEW"
            elif index == len(stages) - 1:
                system_type = "FINISH"
            else:
                system_type = "PROGRESS"

        if progress_stage_id is None and system_type in ("PROGRESS", "WORK", "REVIEW"):
            progress_stage_id = stage_id

    if progress_stage_id is None and len(stages) >= 2:
        progress_stage_id = int(stages[1]["ID"])

    return progress_stage_id, finish_stage_id


async def _update_task_progress(
    client: BitrixClient,
    project_id: int,
    task_etap: str,
    task_zadacha: str,
    stage_id: Optional[int],
    comment: str,
) -> None:
    """
    Move the Bitrix CRM task to a kanban stage, post a comment, and update
    'Дата нач. факт' + '% выполнения факт' in the "2. Этапы и задачи" list.
    All errors are logged as warnings — never raises to the caller.
    """
    if not stage_id and not comment:
        return

    try:
        # --- Find list element for this (Этап, Задача) ---
        ctx = await _get_list_context(client, project_id, "задач")
        if not ctx:
            logger.warning(f"Task progress: 'задач' list not found for project {project_id}")
            return

        list_id, iblock_code, field_map, elements = ctx

        pid_etap = lists._resolve_filter_pid(field_map, "этап")
        pid_zadacha = lists._resolve_filter_pid(field_map, "задача")
        pid_btask_id = lists._resolve_filter_pid(field_map, "bitrix task id")
        pid_start_fact = lists._resolve_filter_pid(field_map, "нач. факт")
        if not pid_start_fact:
            pid_start_fact = lists._resolve_filter_pid(field_map, "нач факт")
        pid_end_fact = lists._resolve_filter_pid(field_map, "ок. факт")
        if not pid_end_fact:
            pid_end_fact = lists._resolve_filter_pid(field_map, "ок факт")

        # "Готовн. Факт" is the existing Excel column for % completion (no extra field created).
        # Must NOT match "Готовн. план" — so use a more specific keyword.
        pid_pct_fact = lists._resolve_filter_pid(field_map, "готовн. факт")
        if not pid_pct_fact:
            pid_pct_fact = lists._resolve_filter_pid(field_map, "готовн факт")

        # Find the matching element
        matched = lists.find_elements_by_properties(
            elements, field_map, {"Этап": task_etap, "Задача": task_zadacha},
        )
        if not matched:
            # Fall back: match by NAME alone
            matched = [e for e in elements if e.get("NAME", "").strip().lower() == task_zadacha.lower()]

        elem = matched[0] if matched else None

        # --- Resolve Bitrix CRM task ID ---
        bitrix_task_id: Optional[int] = None
        if elem and pid_btask_id:
            raw = lists.get_prop_value(elem, pid_btask_id)
            bitrix_task_id = int(raw) if raw else None

        if not bitrix_task_id:
            # Fallback: find by title
            bitrix_task_id = await tasks_methods.find_task_by_title(client, project_id, task_zadacha)
            if bitrix_task_id:
                logger.info(f"Task progress: found task {bitrix_task_id} via title search for '{task_zadacha}'")
            else:
                logger.warning(f"Task progress: CRM task not found for '{task_zadacha}' in project {project_id}")

        # --- Move to stage ---
        all_stages: list[dict] = []
        stage_system_type: Optional[str] = None
        if stage_id and bitrix_task_id:
            try:
                all_stages = await tasks_methods.get_task_stages(client, project_id)
                stage_system_type = _resolve_stage_system_type(all_stages, stage_id)
                await tasks_methods.move_task_to_stage(client, bitrix_task_id, stage_id)
                logger.info(f"Task progress: moved task {bitrix_task_id} to stage {stage_id} ({stage_system_type})")
            except Exception as e:
                logger.warning(f"Task progress: failed to move task {bitrix_task_id} to stage {stage_id}: {e}")

        # --- Task lifecycle (start / complete) ---
        if stage_id and bitrix_task_id and stage_system_type:
            try:
                if stage_system_type == "FINISH":
                    await tasks_methods.complete_task(client, bitrix_task_id)
                    logger.info(f"Task progress: completed task {bitrix_task_id}")
                elif stage_system_type not in ("NEW",):
                    await tasks_methods.start_task(client, bitrix_task_id)
                    logger.info(f"Task progress: started task {bitrix_task_id}")
            except Exception as e:
                logger.warning(f"Task progress: lifecycle call failed for task {bitrix_task_id}: {e}")

        # --- Add comment ---
        if comment and bitrix_task_id:
            try:
                await tasks_methods.add_task_comment(client, bitrix_task_id, comment)
                logger.info(f"Task progress: added comment to task {bitrix_task_id}")
            except Exception as e:
                logger.warning(f"Task progress: failed to add comment to task {bitrix_task_id}: {e}")

        # --- Update list element (Дата нач. факт + Дата ок. факт + % выполнения факт) ---
        sqlite_pct: Optional[float] = None
        sqlite_start: Optional[str] = None
        sqlite_end: Optional[str] = None
        if elem and stage_id:
            elem_id = int(elem["ID"])
            new_vals: Dict[int, Any] = lists.extract_all_prop_values(elem)

            # Compute %
            pct = _compute_completion_pct(all_stages, stage_id)
            sqlite_pct = pct
            if pid_pct_fact:
                new_vals[pid_pct_fact] = pct

            is_new_stage = stage_system_type == "NEW"
            is_finish_stage = stage_system_type == "FINISH"

            # Set start date if element has none and stage is not NEW
            if pid_start_fact and not is_new_stage:
                cur_start = lists.get_prop_value_str(elem, pid_start_fact)
                if not cur_start:
                    today_iso = datetime.now().date().isoformat()
                    new_vals[pid_start_fact] = today_iso
                    sqlite_start = today_iso
                    logger.info(f"Task progress: set Дата нач. факт for element {elem_id}")

            # Set end date if stage is FINISH and not already set
            if pid_end_fact and is_finish_stage:
                cur_end = lists.get_prop_value_str(elem, pid_end_fact)
                if not cur_end:
                    today_iso = datetime.now().date().isoformat()
                    new_vals[pid_end_fact] = today_iso
                    sqlite_end = today_iso
                    logger.info(f"Task progress: set Дата ок. факт for element {elem_id}")

            if pid_pct_fact or pid_start_fact or pid_end_fact:
                await lists.update_element(
                    client, list_id, iblock_code, project_id, elem_id, new_vals,
                    name=elem.get("NAME"),
                )
                logger.info(f"Task progress: updated element {elem_id} — % = {pct}")

        # --- Mirror stage / completion to SQLite so the director agent sees it ---
        if stage_id:
            stage_name = tasks_methods.stage_display_name(all_stages, stage_id)
            try:
                async with get_db() as db_conn:
                    await repo.update_task_progress(
                        db_conn, project_id, task_etap, task_zadacha,
                        completion_pct=sqlite_pct,
                        stage_id=str(stage_id),
                        stage_name=stage_name,
                        date_start_actual=sqlite_start,
                        date_end_actual=sqlite_end,
                    )
            except Exception as mirror_err:
                logger.warning(
                    f"Task progress: SQLite mirror failed for {task_etap}/{task_zadacha}: {mirror_err}"
                )

    except Exception as e:
        logger.error(f"Task progress update failed [{task_etap}/{task_zadacha}]: {e}", exc_info=True)


async def _update_subtask_progress(
    client: BitrixClient,
    project_id: int,
    task_etap: str,
    task_zadacha: str,
    subtask_updates: list[dict],
    comment: str,
) -> None:
    """
    Mark subtasks as started/done, recompute parent task progress %, and
    auto-advance the parent Kanban stage. All errors are logged — never raises.

    subtask_updates: [{element_id: int, status: "started"|"done"}, ...]
    """
    if not subtask_updates and not comment:
        return

    try:
        # --- Get подзадачи list ---
        sub_ctx = await _get_list_context(client, project_id, "подзадач")
        if not sub_ctx:
            # No subtasks list — fall back to kanban-based progress (v3 project)
            return

        sub_list_id, sub_iblock, sub_field_map, sub_elements = sub_ctx

        pid_status = lists._resolve_filter_pid(sub_field_map, "статус")
        pid_start_fact = lists._resolve_filter_pid(sub_field_map, "нач. факт")
        if not pid_start_fact:
            pid_start_fact = lists._resolve_filter_pid(sub_field_map, "нач факт")
        pid_end_fact = lists._resolve_filter_pid(sub_field_map, "ок. факт")
        if not pid_end_fact:
            pid_end_fact = lists._resolve_filter_pid(sub_field_map, "ок факт")
        pid_bsubtask_id = lists._resolve_filter_pid(sub_field_map, "bitrix subtask id")

        update_element_ids = {int(u["element_id"]) for u in subtask_updates if u.get("element_id")}
        today_str = datetime.now().date().isoformat()
        subtask_comment_lines: list[str] = []

        for update in subtask_updates:
            raw_elem_id = update.get("element_id")
            status_req = update.get("status", "")  # "started" or "done"
            if not raw_elem_id or not status_req:
                continue

            elem_id = int(raw_elem_id)
            elem = next((e for e in sub_elements if int(e.get("ID", -1)) == elem_id), None)
            if not elem:
                logger.warning(f"Subtask progress: element {elem_id} not found in project {project_id}")
                continue

            new_vals: Dict[int, Any] = lists.extract_all_prop_values(elem)

            if status_req == "started":
                if pid_status:
                    new_vals[pid_status] = "В работе"
                if pid_start_fact:
                    cur = lists.get_prop_value_str(elem, pid_start_fact)
                    if not cur:
                        new_vals[pid_start_fact] = today_str
            elif status_req == "done":
                if pid_status:
                    new_vals[pid_status] = "Завершена"
                if pid_start_fact:
                    cur = lists.get_prop_value_str(elem, pid_start_fact)
                    if not cur:
                        new_vals[pid_start_fact] = today_str
                if pid_end_fact:
                    cur = lists.get_prop_value_str(elem, pid_end_fact)
                    if not cur:
                        new_vals[pid_end_fact] = today_str

            await lists.update_element(
                client, sub_list_id, sub_iblock, project_id, elem_id, new_vals,
                name=elem.get("NAME"),
            )
            logger.info(f"Subtask progress: updated element {elem_id} → {status_req}")

            sub_title = elem.get("NAME", f"element {elem_id}")
            if status_req == "done":
                subtask_comment_lines.append(f"✅ Подзадача выполнена: {sub_title}")
            elif status_req == "started":
                subtask_comment_lines.append(f"▶️ Подзадача начата: {sub_title}")

        # --- Recompute parent task progress % ---
        # Fetch all subtasks for this (Этап, Задача) fresh to get updated statuses
        sub_elements_fresh = await lists.get_elements(client, sub_list_id, sub_iblock, project_id)
        task_subtasks = lists.find_elements_by_properties(
            sub_elements_fresh, sub_field_map, {"Этап": task_etap, "Задача": task_zadacha},
        )

        total = len(task_subtasks)
        completed = 0
        any_started = False
        for e in task_subtasks:
            st = lists.get_prop_value_str(e, pid_status) if pid_status else ""
            if st and "завершен" in st.lower():
                completed += 1
            if st and ("работ" in st.lower() or "завершен" in st.lower()):
                any_started = True

        pct = round(completed / total * 100, 1) if total > 0 else 0.0

        # --- Update задачи list element ---
        task_ctx = await _get_list_context(client, project_id, "задач")
        if task_ctx:
            t_list_id, t_iblock, t_field_map, t_elements = task_ctx

            pid_pct_fact = lists._resolve_filter_pid(t_field_map, "готовн. факт")
            if not pid_pct_fact:
                pid_pct_fact = lists._resolve_filter_pid(t_field_map, "готовн факт")
            pid_t_start_fact = lists._resolve_filter_pid(t_field_map, "нач. факт")
            if not pid_t_start_fact:
                pid_t_start_fact = lists._resolve_filter_pid(t_field_map, "нач факт")
            pid_t_end_fact = lists._resolve_filter_pid(t_field_map, "ок. факт")
            if not pid_t_end_fact:
                pid_t_end_fact = lists._resolve_filter_pid(t_field_map, "ок факт")
            pid_btask_id = lists._resolve_filter_pid(t_field_map, "bitrix task id")

            matched = lists.find_elements_by_properties(
                t_elements, t_field_map, {"Этап": task_etap, "Задача": task_zadacha},
            )
            if not matched:
                matched = [e for e in t_elements if e.get("NAME", "").strip().lower() == task_zadacha.lower()]

            if matched:
                t_elem = matched[0]
                t_elem_id = int(t_elem["ID"])
                t_vals: Dict[int, Any] = lists.extract_all_prop_values(t_elem)

                if pid_pct_fact:
                    t_vals[pid_pct_fact] = pct

                if pid_t_start_fact and any_started:
                    cur = lists.get_prop_value_str(t_elem, pid_t_start_fact)
                    if not cur:
                        t_vals[pid_t_start_fact] = today_str

                if pid_t_end_fact and pct >= 100.0:
                    cur = lists.get_prop_value_str(t_elem, pid_t_end_fact)
                    if not cur:
                        t_vals[pid_t_end_fact] = today_str

                await lists.update_element(
                    client, t_list_id, t_iblock, project_id, t_elem_id, t_vals,
                    name=t_elem.get("NAME"),
                )
                logger.info(f"Subtask progress: parent task {task_zadacha} → {pct}% ({completed}/{total})")

                # --- Auto-advance parent Kanban stage ---
                bitrix_task_id: Optional[int] = None
                if pid_btask_id:
                    raw = lists.get_prop_value(t_elem, pid_btask_id)
                    bitrix_task_id = int(raw) if raw else None
                if not bitrix_task_id:
                    bitrix_task_id = await tasks_methods.find_task_by_title(client, project_id, task_zadacha)

                if bitrix_task_id:
                    try:
                        all_stages = await tasks_methods.get_task_stages(client, project_id)
                        progress_stage_id, finish_stage_id = _resolve_parent_stage_targets(all_stages)
                        if pct >= 100.0:
                            if finish_stage_id:
                                await tasks_methods.move_task_to_stage(client, bitrix_task_id, finish_stage_id)
                                logger.info(
                                    f"Subtask progress: moved parent task {bitrix_task_id} to FINISH stage {finish_stage_id}",
                                )
                            else:
                                logger.warning(
                                    f"Subtask progress: FINISH stage not resolved for project {project_id}",
                                )
                            await tasks_methods.complete_task(client, bitrix_task_id)
                        elif any_started:
                            if progress_stage_id:
                                await tasks_methods.move_task_to_stage(client, bitrix_task_id, progress_stage_id)
                                logger.info(
                                    "Subtask progress: moved parent task "
                                    f"{bitrix_task_id} to progress stage {progress_stage_id}",
                                )
                            else:
                                logger.warning(
                                    f"Subtask progress: PROGRESS stage not resolved for project {project_id}",
                                )
                            await tasks_methods.start_task(client, bitrix_task_id)
                        logger.info(f"Subtask progress: Kanban+status synced for parent task {bitrix_task_id}")
                    except Exception as e:
                        logger.warning(f"Subtask progress: Kanban advance failed for task {bitrix_task_id}: {e}")

                    # Post comment to parent task (auto subtask status lines + foreman manual comment)
                    auto_msg = "\n".join(subtask_comment_lines)
                    full_comment = "\n\n".join(filter(None, [auto_msg, comment]))
                    if full_comment:
                        try:
                            await tasks_methods.add_task_comment(client, bitrix_task_id, full_comment)
                        except Exception as e:
                            logger.warning(f"Subtask progress: comment failed for task {bitrix_task_id}: {e}")

    except Exception as e:
        logger.error(f"Subtask progress update failed [{task_etap}/{task_zadacha}]: {e}", exc_info=True)


async def check_subtask_deadlines(
    client: BitrixClient,
    project_id: int,
    project_name: str,
    task_etap: str,
    task_zadacha: str,
) -> None:
    """
    Alert if any non-completed subtask has a deadline in the past.
    Called after every foreman report submission.
    """
    from app.notifications.telegram import send_telegram
    from app.notifications.alerts import _esc  # type: ignore[attr-defined]

    try:
        ctx = await _get_list_context(client, project_id, "подзадач")
        if not ctx:
            return

        _, _, field_map, elements = ctx

        pid_status = lists._resolve_filter_pid(field_map, "статус")
        pid_deadline = lists._resolve_filter_pid(field_map, "ок. план")
        if not pid_deadline:
            pid_deadline = lists._resolve_filter_pid(field_map, "ок план")

        subtasks = lists.find_elements_by_properties(
            elements, field_map, {"Этап": task_etap, "Задача": task_zadacha},
        )

        today = datetime.now().date()
        overdue: list[tuple[str, str]] = []  # (title, deadline_str)

        for elem in subtasks:
            status = lists.get_prop_value_str(elem, pid_status) if pid_status else ""
            if status and "завершен" in status.lower():
                continue

            deadline_str = lists.get_prop_value_str(elem, pid_deadline) if pid_deadline else None
            if not deadline_str:
                continue

            try:
                deadline_date = datetime.strptime(deadline_str[:10], "%Y-%m-%d").date()
                if deadline_date < today:
                    overdue.append((elem.get("NAME", ""), deadline_str[:10]))
            except ValueError:
                pass

        for sub_title, sub_deadline in overdue:
            msg = (
                f"⏰ <b>Подзадача просрочена</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏗 Проект: {_esc(project_name)}\n"
                f"📋 Этап: {_esc(task_etap)}\n"
                f"📌 Задача: {_esc(task_zadacha)}\n"
                f"🔸 Подзадача: {_esc(sub_title)}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📅 Срок был: {sub_deadline}"
            )
            await send_telegram(msg)
            logger.info(f"Subtask overdue alert sent: {sub_title} ({sub_deadline})")

    except Exception as e:
        logger.warning(f"check_subtask_deadlines failed [{task_etap}/{task_zadacha}]: {e}")


async def _sync_task_entry_to_bitrix(project_id: int, task_entry: dict) -> None:
    """Push one task_entry's materials/labor/equipment deltas to Bitrix lists.

    SQLite has already been updated synchronously by api_report; this function
    only mirrors to Bitrix. Errors are logged but never raised.
    """
    task_etap    = task_entry.get("task_etap", "").strip()
    task_zadacha = task_entry.get("task_zadacha", "").strip()
    materials    = task_entry.get("materials", [])
    labor        = task_entry.get("labor", [])
    equipment    = task_entry.get("equipment", [])

    if materials:
        try:
            async with BitrixClient() as client:
                ctx = await _get_list_context(client, project_id, "материал")
                if ctx:
                    mat_list_id, mat_iblock, mat_field_map, mat_elements = ctx
                    pid_qty_spent = next(
                        (pid for fname, pid in mat_field_map.items() if "израсходовано" in fname.lower()),
                        None,
                    )
                    pid_cost_spent = next(
                        (pid for fname, pid in mat_field_map.items() if "стоим" in fname.lower() and "факт" in fname.lower()),
                        None,
                    )
                    pid_stock = next(
                        (pid for fname, pid in mat_field_map.items() if "остаток" in fname.lower()),
                        None,
                    )
                    pid_price_fact = next(
                        (pid for fname, pid in mat_field_map.items() if "цена ед" in fname.lower() and "факт" in fname.lower()),
                        None,
                    )
                    pid_price_plan = next(
                        (pid for fname, pid in mat_field_map.items() if "цена ед" in fname.lower() and "план" in fname.lower()),
                        None,
                    )
                    for mat in materials:
                        mat_name = mat.get("name", "").strip()
                        qty_used = float(mat.get("quantity") or 0)
                        if not mat_name or qty_used == 0:
                            continue
                        if task_etap and task_zadacha:
                            matched = lists.find_elements_by_properties(
                                mat_elements, mat_field_map,
                                {"Этап": task_etap, "Задача": task_zadacha},
                            )
                            elem = lists.find_element_by_name(matched, mat_name)
                        else:
                            elem = lists.find_element_by_name(mat_elements, mat_name)
                        if not elem:
                            logger.warning(f"BG report sync: material '{mat_name}' not found in project {project_id}")
                            continue
                        element_id_mat = int(elem["ID"])
                        new_vals: Dict[int, Any] = lists.extract_all_prop_values(elem)
                        if pid_qty_spent:
                            cur = lists.get_prop_value(elem, pid_qty_spent) or 0.0
                            new_vals[pid_qty_spent] = cur + qty_used
                        if pid_stock:
                            cur = lists.get_prop_value(elem, pid_stock) or 0.0
                            new_vals[pid_stock] = max(0.0, cur - qty_used)
                        if pid_cost_spent:
                            price = (
                                (lists.get_prop_value(elem, pid_price_fact) if pid_price_fact else None)
                                or (lists.get_prop_value(elem, pid_price_plan) if pid_price_plan else None)
                                or 0.0
                            )
                            cur = lists.get_prop_value(elem, pid_cost_spent) or 0.0
                            new_vals[pid_cost_spent] = cur + qty_used * price
                        if new_vals:
                            await lists.update_element(client, mat_list_id, mat_iblock, project_id, element_id_mat, new_vals, name=mat_name)
                            logger.info(f"BG report sync: updated material '{mat_name}' [{task_etap}/{task_zadacha}]")
        except Exception as sync_err:
            logger.error(f"BG report sync (materials) failed for project {project_id}: {sync_err}", exc_info=True)

    if labor:
        try:
            async with BitrixClient() as client:
                ctx = await _get_list_context(client, project_id, "трудозатрат")
                if ctx:
                    lab_list_id, lab_iblock, lab_field_map, lab_elements = ctx
                    pid_hours_fact = next(
                        (pid for fname, pid in lab_field_map.items() if "факт" in fname.lower() and "час" in fname.lower()),
                        None,
                    )
                    pid_rate = next(
                        (pid for fname, pid in lab_field_map.items() if "ставка" in fname.lower()),
                        None,
                    )
                    pid_fot_fact = next(
                        (pid for fname, pid in lab_field_map.items() if "фот" in fname.lower() and "факт" in fname.lower()),
                        None,
                    )
                    for worker in labor:
                        worker_name = worker.get("worker_name", "").strip()
                        hours = float(worker.get("hours") or 0)
                        if not worker_name or hours == 0:
                            continue
                        if task_etap and task_zadacha:
                            matched = lists.find_elements_by_properties(
                                lab_elements, lab_field_map,
                                {"Этап": task_etap, "Задача": task_zadacha},
                            )
                            elem = lists.find_element_by_name(matched, worker_name)
                        else:
                            elem = lists.find_element_by_name(lab_elements, worker_name)
                        if not elem:
                            logger.warning(f"BG report sync: worker '{worker_name}' not found in project {project_id}")
                            continue
                        element_id_lab = int(elem["ID"])
                        new_vals_lab: Dict[int, Any] = lists.extract_all_prop_values(elem)
                        if pid_hours_fact:
                            cur = lists.get_prop_value(elem, pid_hours_fact) or 0.0
                            total_hours = cur + hours
                            new_vals_lab[pid_hours_fact] = total_hours
                            if pid_fot_fact and pid_rate:
                                rate = lists.get_prop_value(elem, pid_rate) or 0.0
                                new_vals_lab[pid_fot_fact] = round(total_hours * rate, 2)
                        if new_vals_lab:
                            await lists.update_element(client, lab_list_id, lab_iblock, project_id, element_id_lab, new_vals_lab, name=worker_name)
                            logger.info(f"BG report sync: updated labor '{worker_name}' [{task_etap}/{task_zadacha}]")
        except Exception as sync_err:
            logger.error(f"BG report sync (labor) failed for project {project_id}: {sync_err}", exc_info=True)

    if equipment:
        try:
            async with BitrixClient() as client:
                ctx = await _get_list_context(client, project_id, "техник")
                if ctx:
                    eq_list_id, eq_iblock, eq_field_map, eq_elements = ctx
                    pid_hours_fact_eq = next(
                        (pid for fname, pid in eq_field_map.items() if "факт" in fname.lower() and "час" in fname.lower()),
                        None,
                    )
                    pid_price_hour = next(
                        (pid for fname, pid in eq_field_map.items() if "цена" in fname.lower() and "час" in fname.lower()),
                        None,
                    )
                    pid_total_fact = next(
                        (pid for fname, pid in eq_field_map.items() if "итого" in fname.lower() and "факт" in fname.lower()),
                        None,
                    )
                    for eq in equipment:
                        eq_name = eq.get("name", "").strip()
                        hours = float(eq.get("hours") or 0)
                        if not eq_name or hours == 0:
                            continue
                        if task_etap and task_zadacha:
                            matched = lists.find_elements_by_properties(
                                eq_elements, eq_field_map,
                                {"Этап": task_etap, "Задача": task_zadacha},
                            )
                            elem = lists.find_element_by_name(matched, eq_name)
                        else:
                            elem = lists.find_element_by_name(eq_elements, eq_name)
                        if not elem:
                            logger.warning(f"BG report sync: equipment '{eq_name}' not found in project {project_id}")
                            continue
                        element_id_eq = int(elem["ID"])
                        new_vals_eq: Dict[int, Any] = lists.extract_all_prop_values(elem)
                        if pid_hours_fact_eq:
                            cur = lists.get_prop_value(elem, pid_hours_fact_eq) or 0.0
                            total_hours = cur + hours
                            new_vals_eq[pid_hours_fact_eq] = total_hours
                            if pid_total_fact and pid_price_hour:
                                qty = lists.get_prop_value(elem, lists._resolve_filter_pid(eq_field_map, "кол-во") or 0) or 1.0
                                price = lists.get_prop_value(elem, pid_price_hour) or 0.0
                                new_vals_eq[pid_total_fact] = round(qty * price * total_hours, 2)
                        if new_vals_eq:
                            await lists.update_element(client, eq_list_id, eq_iblock, project_id, element_id_eq, new_vals_eq, name=eq_name)
                            logger.info(f"BG report sync: updated equipment '{eq_name}' [{task_etap}/{task_zadacha}]")
        except Exception as sync_err:
            logger.error(f"BG report sync (equipment) failed for project {project_id}: {sync_err}", exc_info=True)


async def _background_report_tasks(
    project_id: int,
    tasks_entries: list,
    report_project_name: str,
    report_date: str,
    comments: str,
) -> None:
    """
    All Bitrix-side work for a foreman report: create the report list element,
    sync materials/labor/equipment to Bitrix lists, run cascade, update task
    progress, run notifications. Runs after the HTTP 200 has been returned.

    SQLite is already updated synchronously in api_report — this function does
    not write to SQLite (Bitrix is the display mirror).
    """
    # 1. Create the Bitrix report list element
    try:
        async with BitrixClient() as client:
            report_info = await lists.get_or_create_report_list(client, project_id)
            list_id = report_info["list_id"]
            iblock_code = report_info["iblock_code"]
            field_ids = report_info["field_ids"]
            field_values: dict[int, str] = {}
            if "f_0_date" in field_ids:
                field_values[field_ids["f_0_date"]] = report_date
            if "f_1_author" in field_ids:
                field_values[field_ids["f_1_author"]] = "Прораб"
            if "f_2_comments" in field_ids:
                field_values[field_ids["f_2_comments"]] = comments
            if "f_3_materials" in field_ids:
                all_mats = [m for t in tasks_entries for m in t.get("materials", [])]
                field_values[field_ids["f_3_materials"]] = json.dumps(all_mats, ensure_ascii=False)
            if "f_4_labor" in field_ids:
                all_lab = [l for t in tasks_entries for l in t.get("labor", [])]
                field_values[field_ids["f_4_labor"]] = json.dumps(all_lab, ensure_ascii=False)
            element_code = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            await lists.add_element(
                client, list_id=list_id, iblock_code=iblock_code,
                group_id=project_id, element_code=element_code,
                name=f"Отчет {report_date}", field_values=field_values,
            )
    except Exception as e:
        logger.error(f"BG report-element create failed for project {project_id}: {e}", exc_info=True)

    # 2. Bitrix material/labor/equipment sync per task entry
    for task_entry in tasks_entries:
        await _sync_task_entry_to_bitrix(project_id, task_entry)

    # 3. Cascade + task progress + notifications (existing logic)
    for task_entry in tasks_entries:
        task_etap      = task_entry.get("task_etap", "").strip()
        task_zadacha   = task_entry.get("task_zadacha", "").strip()
        materials      = task_entry.get("materials", [])
        stage_id       = task_entry.get("stage_id")
        task_comment   = task_entry.get("comment", "").strip()
        subtask_updates = task_entry.get("subtask_updates", [])
        if stage_id is not None:
            try:
                stage_id = int(stage_id)
            except (TypeError, ValueError):
                stage_id = None

        # Cascade
        if task_etap and task_zadacha:
            try:
                async with BitrixClient() as client:
                    await cascade_update_task(client, project_id, task_etap, task_zadacha)
                    await cascade_update_budget(client, project_id, task_etap)
            except Exception as e:
                logger.error(f"BG cascade failed [{task_etap}/{task_zadacha}]: {e}", exc_info=True)

        # Task progress: subtask-based (v4) or kanban-based (v3) fallback
        if task_etap and task_zadacha:
            if subtask_updates:
                try:
                    async with BitrixClient() as client:
                        await _update_subtask_progress(
                            client, project_id, task_etap, task_zadacha,
                            subtask_updates, task_comment,
                        )
                except Exception as e:
                    logger.error(f"BG subtask progress failed [{task_etap}/{task_zadacha}]: {e}", exc_info=True)
            elif stage_id or task_comment:
                try:
                    async with BitrixClient() as client:
                        await _update_task_progress(
                            client, project_id, task_etap, task_zadacha, stage_id, task_comment
                        )
                except Exception as e:
                    logger.error(f"BG task progress failed [{task_etap}/{task_zadacha}]: {e}", exc_info=True)

        # Notifications
        try:
            async with BitrixClient() as client:
                for mat in materials:
                    mat_name = mat.get("name", "").strip()
                    if mat_name:
                        await check_consumption_ratio(
                            client, project_id, report_project_name, mat_name,
                        )

                mat_ctx = await _get_list_context(client, project_id, "материал")
                if mat_ctx:
                    _, _, _nf_fm, _nf_elems = mat_ctx
                    _nf_pid_stock = next(
                        (pid for n, pid in _nf_fm.items() if "остаток" in n.lower()), None
                    )
                    _nf_pid_plan = next(
                        (pid for n, pid in _nf_fm.items() if "объём план" in n.lower()), None
                    )
                    _nf_pid_bought = next(
                        (pid for n, pid in _nf_fm.items()
                         if "куплено" in n.lower() and "объём" in n.lower()), None
                    )
                    for mat in materials:
                        mat_name = mat.get("name", "").strip()
                        if not mat_name:
                            continue
                        if task_etap and task_zadacha:
                            _matched = lists.find_elements_by_properties(
                                _nf_elems, _nf_fm,
                                {"Этап": task_etap, "Задача": task_zadacha},
                            )
                            _elem = lists.find_element_by_name(_matched, mat_name)
                        else:
                            _elem = lists.find_element_by_name(_nf_elems, mat_name)
                        if _elem and _nf_pid_stock and _nf_pid_plan:
                            _stock = float(lists.get_prop_value(_elem, _nf_pid_stock) or 0)
                            _plan = float(lists.get_prop_value(_elem, _nf_pid_plan) or 0)
                            _bought = float(lists.get_prop_value(_elem, _nf_pid_bought) or 0) if _nf_pid_bought else 0.0
                            await check_warehouse_balance(
                                report_project_name, mat_name,
                                _stock, _plan, _bought,
                            )

                if task_etap and task_zadacha:
                    task_ctx = await _get_list_context(client, project_id, "задач")
                    if task_ctx:
                        _, _, _tf_fm, _tf_elems = task_ctx
                        _matched_tasks = lists.find_elements_by_properties(
                            _tf_elems, _tf_fm,
                            {"Этап": task_etap, "Задача": task_zadacha},
                        )
                        if _matched_tasks:
                            _te = _matched_tasks[0]
                            _pid_bp = lists._resolve_filter_pid(_tf_fm, "бюджет план")
                            _pid_bf = lists._resolve_filter_pid(_tf_fm, "бюджет факт")
                            _pid_pct = lists._resolve_filter_pid(_tf_fm, "готовн. факт")
                            if not _pid_pct:
                                _pid_pct = lists._resolve_filter_pid(_tf_fm, "готовн факт")
                            _pid_sp = next(
                                (pid for n, pid in _tf_fm.items() if "нач" in n.lower() and "план" in n.lower()), None
                            )
                            _pid_ep = next(
                                (pid for n, pid in _tf_fm.items() if "ок" in n.lower() and "план" in n.lower()), None
                            )
                            _pct_val = float(lists.get_prop_value(_te, _pid_pct) or 0) if _pid_pct else 0.0
                            _bp_val = float(lists.get_prop_value(_te, _pid_bp) or 0) if _pid_bp else 0.0
                            _bf_val = float(lists.get_prop_value(_te, _pid_bf) or 0) if _pid_bf else 0.0
                            await check_budget_threshold(
                                report_project_name, task_zadacha, task_etap,
                                _bp_val, _bf_val, _pct_val,
                            )
                            _sp_val = lists.get_prop_value_str(_te, _pid_sp) if _pid_sp else None
                            _ep_val = lists.get_prop_value_str(_te, _pid_ep) if _pid_ep else None
                            await check_schedule_slippage(
                                report_project_name, task_zadacha, task_etap,
                                _sp_val, _ep_val, _pct_val,
                            )

                if task_etap and task_zadacha:
                    await check_subtask_deadlines(
                        client, project_id, report_project_name, task_etap, task_zadacha,
                    )
        except Exception as notif_err:
            logger.warning(f"BG notifications failed: {notif_err}")


@router.post("/api/buyer-report")
async def api_buyer_report_legacy(request: Request) -> JSONResponse:
    """
    Deprecated. The buyer report no longer applies a purchase directly to "3. Материалы".

    Procurement now goes through the approval flow at POST /api/purchase-request: the
    buyer attaches a counterparty document, the approver reviews on /approval/{id}, and
    only an Approve action moves the warehouse / weighted-price numbers.
    """
    return JSONResponse(
        status_code=410,
        content={
            "success": False,
            "error": "deprecated",
            "detail": (
                "POST /api/buyer-report removed. Use POST /api/purchase-request "
                "(multipart/form-data) to submit a purchase request for approval."
            ),
        },
    )


@router.post("/api/purchase-request")
async def api_purchase_request(
    background: BackgroundTasks,
    project_id: int = Form(...),
    items_json: str = Form(...),
    proposal: UploadFile = File(...),
    buyer_comment: str = Form(default=""),
) -> JSONResponse:
    """
    Submit a procurement approval request.

    Form fields:
        project_id     — Bitrix workgroup id (int)
        items_json     — JSON array of {material_name, qty, price, unit?, price_plan?}
        proposal       — REQUIRED commercial-proposal file (PDF only, ≤MAX_PROPOSAL_FILE_MB)
        buyer_comment  — REQUIRED when any item's price exceeds its price_plan
                         (justification of the overspend)

    Author/etap/zadacha will be derived from the authenticated Bitrix user once
    BX24.callMethod('user.current') is wired in. Until then we hardcode
    author = "Закупщик" (user_id = 1).
    """
    from app.purchase_requests import create_request

    try:
        items = json.loads(items_json) if items_json else []
        if not isinstance(items, list) or not items:
            raise ValueError("items_json must be a non-empty array")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"items_json invalid: {e}")

    # Server-side enforcement of "comment required when price > plan".
    over_plan_items = []
    for it in items:
        try:
            price = float(it.get("price") or 0)
            plan = float(it.get("price_plan") or 0)
        except (TypeError, ValueError):
            continue
        if plan > 0 and price > plan:
            over_plan_items.append(it.get("material_name") or "?")
    if over_plan_items and not buyer_comment.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "Комментарий обязателен: цена превышает план для позиций: "
                + ", ".join(over_plan_items)
            ),
        )

    file_bytes = await proposal.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Файл коммерческого предложения обязателен")
    max_bytes = settings.max_proposal_file_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds limit of {settings.max_proposal_file_mb} MB",
        )
    file_name = proposal.filename or "proposal.pdf"
    ext = (file_name.split(".")[-1] or "").lower()
    if ext != "pdf":
        raise HTTPException(
            status_code=415, detail="Допускаются только PDF-файлы",
        )

    project_name = f"Проект #{project_id}"
    try:
        async with get_db() as db_conn:
            for p in await repo.get_projects(db_conn):
                if int(p["id"]) == project_id:
                    project_name = p.get("name", project_name)
                    break
    except Exception:
        pass

    async with BitrixClient() as client:
        result = await create_request(
            client,
            project_id=project_id,
            project_name=project_name,
            items=items,
            file_name=file_name,
            file_bytes=file_bytes,
            author="Закупщик",
            etap="",
            zadacha="",
            buyer_comment=buyer_comment.strip(),
        )

    audit_inputs = result.get("_audit_task_inputs")
    if audit_inputs:
        from app.purchase_requests import create_audit_task_background
        background.add_task(create_audit_task_background, audit_inputs)

    return JSONResponse(content={
        "success": True,
        "request_id": result["request_id"],
        "request_no": result["request_no"],
        "task_id": result["task_id"],
    })


@router.post("/api/report")
async def api_report(request: Request, background: BackgroundTasks) -> JSONResponse:
    """
    Submit a foreman daily report.

    Synchronous path: validate, write deltas to SQLite, run SQLite cascade.
    Background path: create Bitrix report element, mirror to Bitrix lists,
    run Bitrix cascade, update task progress, run notifications.

    SQLite is the source of truth for the response — Bitrix is an async mirror.
    """
    body = await request.json()

    project_id = body.get("project_id")
    report_date = body.get("date", "")
    comments = body.get("comments", "")

    # Support both new multi-task format (tasks=[]) and legacy flat format
    tasks_entries = body.get("tasks", [])
    if not tasks_entries:
        tasks_entries = [{
            "task_etap": body.get("task_etap", "").strip(),
            "task_zadacha": body.get("task_zadacha", "").strip(),
            "materials": body.get("materials", []),
            "labor": body.get("labor", []),
            "equipment": body.get("equipment", []),
        }]

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    project_id = int(project_id)

    # --- Synchronous: SQLite writes only ---
    report_project_name = f"Проект #{project_id}"
    try:
        async with get_db() as db_conn:
            projects_rows = await repo.get_projects(db_conn)
            for p in projects_rows:
                if int(p["id"]) == project_id:
                    report_project_name = p.get("name", report_project_name)
                    break

            cascade_pairs: set[tuple[str, str]] = set()
            cascade_phases: set[str] = set()

            for task_entry in tasks_entries:
                task_etap    = task_entry.get("task_etap", "").strip()
                task_zadacha = task_entry.get("task_zadacha", "").strip()
                materials    = task_entry.get("materials", [])
                labor        = task_entry.get("labor", [])
                equipment    = task_entry.get("equipment", [])

                if task_etap and task_zadacha:
                    cascade_pairs.add((task_etap, task_zadacha))
                    cascade_phases.add(task_etap)

                for mat in materials:
                    mat_name = (mat.get("name") or "").strip()
                    qty_used = float(mat.get("quantity") or 0)
                    if not mat_name or qty_used == 0:
                        continue
                    plan_row = await repo.get_material_row(
                        db_conn, project_id, task_etap, task_zadacha, mat_name,
                    ) if task_etap and task_zadacha else None
                    price = 0.0
                    if plan_row:
                        price = float(plan_row.get("price_actual") or 0.0) or float(plan_row.get("price_plan") or 0.0)
                    cost_delta = qty_used * price
                    await repo.update_material_after_report(
                        db_conn, project_id, task_etap, task_zadacha, mat_name,
                        qty_used, cost_delta,
                    )

                for worker in labor:
                    worker_name = (worker.get("worker_name") or "").strip()
                    hours = float(worker.get("hours") or 0)
                    if not worker_name or hours == 0:
                        continue
                    plan_row = await repo.get_labor_row(
                        db_conn, project_id, task_etap, task_zadacha, worker_name,
                    ) if task_etap and task_zadacha else None
                    rate = float(plan_row.get("rate") or 0.0) if plan_row else 0.0
                    payroll_delta = hours * rate
                    await repo.update_labor_after_report(
                        db_conn, project_id, task_etap, task_zadacha, worker_name,
                        hours, payroll_delta,
                    )

                for eq in equipment:
                    eq_name = (eq.get("name") or "").strip()
                    hours = float(eq.get("hours") or 0)
                    if not eq_name or hours == 0:
                        continue
                    plan_row = await repo.get_equipment_row(
                        db_conn, project_id, task_etap, task_zadacha, eq_name,
                    ) if task_etap and task_zadacha else None
                    price_per_hour = float(plan_row.get("price_per_hour") or 0.0) if plan_row else 0.0
                    total_delta = hours * price_per_hour
                    await repo.update_equipment_after_report(
                        db_conn, project_id, task_etap, task_zadacha, eq_name,
                        hours, total_delta,
                    )

            # SQLite cascade: per-task budgets, then per-phase budgets
            for etap, zadacha in cascade_pairs:
                try:
                    await repo.cascade_task_budget(db_conn, project_id, etap, zadacha)
                except Exception as e:
                    logger.warning(f"SQLite cascade_task_budget [{etap}/{zadacha}] failed: {e}")
            for etap in cascade_phases:
                try:
                    await repo.cascade_phase_budget(db_conn, project_id, etap)
                except Exception as e:
                    logger.warning(f"SQLite cascade_phase_budget [{etap}] failed: {e}")

            # Write a budget snapshot for today so the timeline chart has data
            try:
                from datetime import date as _today_date
                today_str = _today_date.today().isoformat()
                phases = await repo.get_budget_phases(db_conn, project_id)
                snap_mat = sum(ph.get("materials_actual") or 0 for ph in phases)
                snap_lab = sum(ph.get("labor_actual") or 0 for ph in phases)
                snap_eq  = sum(ph.get("equipment_actual") or 0 for ph in phases)
                snap_tot = sum(ph.get("total_actual") or 0 for ph in phases)
                await db_conn.execute(
                    """
                    INSERT INTO budget_snapshots(project_id, snapshot_date, mat_actual, lab_actual, eq_actual, total_actual)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(project_id, snapshot_date) DO UPDATE SET
                        mat_actual=excluded.mat_actual,
                        lab_actual=excluded.lab_actual,
                        eq_actual=excluded.eq_actual,
                        total_actual=excluded.total_actual
                    """,
                    (project_id, today_str, snap_mat, snap_lab, snap_eq, snap_tot),
                )
                await db_conn.commit()
            except Exception as e:
                logger.warning(f"Budget snapshot write failed for project {project_id}: {e}")
    except Exception as e:
        logger.error(f"Report SQLite write failed for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(f"Report SQLite write complete for project {project_id}")

    # --- Background: Bitrix mirror + cascade + notifications ---
    background.add_task(
        _background_report_tasks,
        project_id, tasks_entries, report_project_name, report_date, comments,
    )

    domain = settings.bitrix24_domain
    return JSONResponse(content={
        "success": True,
        "link": f"https://{domain}/workgroups/group/{project_id}/lists/",
    })
