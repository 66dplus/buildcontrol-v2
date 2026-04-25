"""
Main orchestrator for Excel import into Bitrix24.
Implements Phases 2-4: Create project, lists, and tasks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in path when running as script
sys.path.insert(0, str(Path(__file__).parent.parent))

from bitrix.client import BitrixClient
from bitrix.methods import lists, tasks, workgroups
from config import settings
from utils.excel_parser import parse_excel_file, get_project_name




logger = logging.getLogger(__name__)


def _deduplicate_labor_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate трудозатраты rows by (Этап, Задача, Специальность/*бригада*).
    Numeric columns (Кол-во чел., Ч-часов план, ФОТ план, etc.) are summed.
    """
    group_keywords = ["этап", "задача", "специальность"]
    groups: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        # Build group key from columns whose header matches any group keyword
        key = tuple(
            str(v).strip() if (v := row.get(h)) is not None else ""
            for h in rows[0].keys()
            if any(kw in h.lower() for kw in group_keywords)
        )
        if key not in groups:
            groups[key] = dict(row)
        else:
            for col, val in row.items():
                if isinstance(val, (int, float)):
                    groups[key][col] = (groups[key].get(col) or 0) + val
    return list(groups.values())


class ExcelImporter:
    """Orchestrates Excel file import to Bitrix24."""

    def __init__(self, client: BitrixClient) -> None:
        """Initialize importer with Bitrix24 client."""
        self.client = client

    async def import_file(self, file_path: str, custom_name: str | None = None) -> Dict[str, Any]:
        """
        Import Excel file into Bitrix24.

        Args:
            file_path: Path to Excel file
            custom_name: Optional project name override (uses filename stem if not provided)

        Returns:
            Import result dict with project_id, list_ids, task_ids

        Raises:
            ValueError: If any API call fails
        """
        logger.info(f"Starting import of {file_path}")

        # Parse Excel file
        excel_data = parse_excel_file(file_path)
        if custom_name:
            # Use user-supplied name verbatim so they see the project exactly
            # as entered.
            project_name = custom_name
        else:
            # Append timestamp so repeated imports of the same file don't collide
            base_name = get_project_name(file_path)
            project_name = f"{base_name} [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
        logger.info(f"Project name: {project_name}, Sheets: {list(excel_data.keys())}")

        result = {
            "project_id": None,
            "list_ids": {},
            "task_ids": [],
            "summary": {},
        }

        # Phase 2: Create project
        project_id = await self._create_project(project_name)
        result["project_id"] = project_id
        logger.info(f"✓ Created project {project_name} (ID: {project_id})")

        # Phase 3: Create lists with data
        list_ids = await self._create_lists(project_id, excel_data)
        result["list_ids"] = list_ids
        logger.info(f"✓ Created lists: {json.dumps({k: v['id'] for k, v in list_ids.items()}, ensure_ascii=False)}")

        # Phase 4: Create tasks from phases sheet + link IDs back into the list
        zadach_list_info = next(
            (v for k, v in list_ids.items() if "задач" in k.lower() and "подзадач" not in k.lower()), None
        )
        task_ids, task_id_map = await self._create_tasks(excel_data, project_id, zadach_list_info=zadach_list_info)
        result["task_ids"] = task_ids
        logger.info(f"✓ Created {len(task_ids)} tasks from phases sheet")

        # Summary
        result["summary"] = {
            "project_id": project_id,
            "project_name": project_name,
            "list_count": len(list_ids),
            "lists": {name: data["row_count"] for name, data in list_ids.items()},
            "task_count": len(task_ids),
            "created_at": datetime.now().isoformat(),
        }

        domain = settings.bitrix24_domain
        result["summary"]["links"] = {
            "project": f"https://{domain}/workgroups/group/{project_id}/",
            "lists": f"https://{domain}/workgroups/group/{project_id}/lists/",
            "tasks": f"https://{domain}/workgroups/group/{project_id}/tasks/",
        }
        logger.info(f"✓ Import complete: {json.dumps(result['summary'], ensure_ascii=False, indent=2)}")
        logger.info(f"🔗 Lists: https://{domain}/workgroups/group/{project_id}/lists/")
        logger.info(f"🔗 Tasks: https://{domain}/workgroups/group/{project_id}/tasks/")
        return result

    async def _create_project(self, name: str) -> int:
        """Create Bitrix24 project from filename, then update description with links."""
        logger.info(f"Creating project: {name}")
        project_id = await workgroups.create_project(
            self.client,
            name=name,
            description=f"Импорт из Excel: {datetime.now().isoformat()}",
        )
        domain = settings.bitrix24_domain
        await self.client.call("sonet_group.update", {
            "GROUP_ID": project_id,
            "DESCRIPTION": (
                f"Импорт из Excel: {datetime.now().isoformat()}\n"
                f"Списки: https://{domain}/workgroups/group/{project_id}/lists/\n"
                f"Задачи: https://{domain}/workgroups/group/{project_id}/tasks/"
            ),
        })
        return project_id

    # Maps a keyword found in the sheet name to the column keyword used as element NAME.
    # Fallback: first column (headers[0]) is used for sheets not in this map (e.g. Бюджет).
    _NAME_COLUMN_KEYWORDS: Dict[str, str] = {
        "подзадач": "название",  # must come before "задач" — "подзадачи" contains "задач"
        "задач": "задача",
        "материал": "наименование",
        "трудозатрат": "специальность",
        "техник": "техника",
    }

    async def _create_lists(
        self, project_id: int, excel_data: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Create Universal Lists for each sheet inside the project.

        Returns:
            Dict mapping sheet names to {id, row_count, field_ids}
        """
        result: Dict[str, Dict[str, Any]] = {}

        for sheet_name, rows in excel_data.items():
            if not rows:
                logger.warning(f"Skipping empty sheet: {sheet_name}")
                continue

            logger.info(f"Creating list for sheet: {sheet_name}")

            # Generate unique iblock_code from project_id + sanitized sheet name
            # Only ASCII alphanumeric allowed in iblock_code (Bitrix24 restriction)
            safe_name = "".join(c if (c.isascii() and c.isalnum()) else "_" for c in sheet_name).lower()
            iblock_code = f"bc_{project_id}_{safe_name}"

            # Create list
            list_id = await lists.create_list(
                self.client,
                name=sheet_name,
                group_id=project_id,
                iblock_code=iblock_code,
                description=f"Data from {sheet_name} sheet",
            )

            # Deduplicate labor rows: group by (Этап, Задача, Специальность), sum numeric cols
            if "трудозатрат" in sheet_name.lower():
                rows = _deduplicate_labor_rows(rows)

            # Get headers from first row
            headers = list(rows[0].keys())
            # field_ids: {header_name -> field_id (int)}
            field_ids: Dict[str, int] = {}

            # Create fields (sort starts at 20, step 10 per field)
            for sort_idx, header in enumerate(headers):
                # Find a sample non-None value for data-driven type detection
                sample = next((r.get(header) for r in rows if r.get(header) is not None), None)
                field_type = self._infer_field_type(header, sample_value=sample)
                # Generate safe field code from header (ASCII only — Bitrix24 restriction)
                safe_code = "".join(c if (c.isascii() and c.isalnum()) else "_" for c in header).lower()[:20]
                safe_code = f"f_{sort_idx}_{safe_code}"
                try:
                    field_id = await lists.add_field(
                        self.client,
                        list_id=list_id,
                        iblock_code=iblock_code,
                        group_id=project_id,
                        name=header,
                        field_code=safe_code,
                        field_type=field_type,
                        sort=(sort_idx + 1) * 10,
                    )
                    field_ids[header] = field_id
                except ValueError as e:
                    logger.warning(f"Failed to create field {header}: {e}")
                    continue

            # Determine which column to use as element NAME based on sheet type
            name_col_key = headers[0]  # default (e.g. Бюджет uses first column)
            for sheet_kw, col_kw in self._NAME_COLUMN_KEYWORDS.items():
                if sheet_kw in sheet_name.lower():
                    match = next((h for h in headers if col_kw in h.lower()), None)
                    if match:
                        name_col_key = match
                    break

            # For "задач" sheet: add 1 extra system field (Bitrix Task ID) after Excel columns.
            # "Дата нач. факт" and "Готовн. Факт" already come from the Excel template — no duplicates.
            # For "подзадач" sheet: add "Bitrix Subtask ID" written back by importer.
            extra_field_ids: Dict[str, int] = {}
            is_zadach_sheet = "задач" in sheet_name.lower() and "подзадач" not in sheet_name.lower()
            is_podzadach_sheet = "подзадач" in sheet_name.lower()
            if is_zadach_sheet:
                extra_fields = [
                    ("f_ext_btask_id", "Bitrix Task ID", "N"),
                ]
            elif is_podzadach_sheet:
                extra_fields = [
                    ("f_ext_bsubtask_id", "Bitrix Subtask ID", "N"),
                ]
            else:
                extra_fields = []
            if extra_fields:
                extra_sort_base = (len(headers) + 1) * 10
                for sort_offset, (code, name, ftype) in enumerate(extra_fields):
                    try:
                        fid = await lists.add_field(
                            self.client,
                            list_id=list_id,
                            iblock_code=iblock_code,
                            group_id=project_id,
                            name=name,
                            field_code=code,
                            field_type=ftype,
                            sort=extra_sort_base + (sort_offset + 1) * 10,
                        )
                        extra_field_ids[code] = fid
                        logger.info(f"  + Added extra field '{name}' (ID: {fid}) to {sheet_name}")
                    except ValueError as e:
                        logger.warning(f"Failed to create extra field '{name}': {e}")

            # Add rows as elements
            element_count = 0
            # element_info_map (zadach sheet only):
            # (etap.lower(), zadacha.lower()) -> [ {"id": elem_id, "field_values": {...}}, ... ]
            # Stored so the task-ID writeback can pass existing properties and avoid wiping them
            # (Bitrix24 lists.element.update REPLACES the field set, does not merge).
            element_info_map: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
            task_col_key = next((h for h in headers if "задача" in h.lower()), None)
            etap_col_key = next((h for h in headers if h.lower().strip() == "этап"), None)
            for row_idx, row_data in enumerate(rows, start=1):
                try:
                    name_val = str(row_data.get(name_col_key) or f"Row {row_idx}")

                    # Skip ИТОГО summary rows — check col 0 (Этап) which always holds "ИТОГО"
                    etap_val = str(row_data.get(headers[0]) or "")
                    if "итого" in etap_val.lower() or "итого" in name_val.lower():
                        logger.info(f"Skipping ИТОГО row in sheet: {sheet_name}")
                        continue

                    # Map header -> field_id -> value
                    field_values = {
                        field_ids[h]: row_data.get(h)
                        for h in headers
                        if h in field_ids and row_data.get(h) is not None
                    }

                    elem_id = await lists.add_element(
                        self.client,
                        list_id=list_id,
                        iblock_code=iblock_code,
                        group_id=project_id,
                        element_code=f"row_{row_idx}",
                        name=name_val,
                        field_values=field_values,
                    )
                    element_count += 1
                    if is_zadach_sheet:
                        task_name = str(row_data.get(task_col_key) or name_val).strip()
                        etap_name = str(row_data.get(etap_col_key) or "").strip()
                        key = (etap_name.lower(), task_name.lower())
                        element_info_map.setdefault(key, []).append({
                            "id": elem_id,
                            "field_values": field_values,
                        })
                except ValueError as e:
                    logger.warning(f"Failed to add element {row_idx} to {sheet_name}: {e}")
                    continue

            logger.info(f"✓ Created list {sheet_name} (ID: {list_id}) with {element_count} rows")
            result[sheet_name] = {
                "id": list_id,
                "iblock_code": iblock_code,
                "row_count": element_count,
                "field_ids": field_ids,
                "extra_field_ids": extra_field_ids,
                "element_info_map": element_info_map,
            }

        return result

    async def _create_tasks(
        self,
        excel_data: Dict[str, List[Dict[str, Any]]],
        project_id: int,
        zadach_list_info: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[int], Dict[tuple, int]]:
        """
        Create Bitrix tasks from "2. Этапы и задачи" sheet (v3 template).

        Each row becomes a task:
        - Title:      "Задача" column
        - Start date: column containing "нач" + "план"  → START_DATE_PLAN
        - End date:   column containing "ок." + "план"  → END_DATE_PLAN (+ DEADLINE)
        - UF_ETAP:    "Этап" column value stored as custom field
        - Responsible: User ID 1 (MVP: hardcoded)
        - Group:      linked to project_id
        """
        sheet_name = "2. Этапы и задачи"
        rows = excel_data.get(sheet_name, [])
        if not rows:
            logger.warning(f"Sheet '{sheet_name}' not found — skipping task creation")
            return [], {}

        sample_keys = list(rows[0].keys())
        title_key = next((k for k in sample_keys if "задача" in k.lower()), None)
        start_key = next((k for k in sample_keys if "нач" in k.lower() and "план" in k.lower()), None)
        end_key   = next(
            (k for k in sample_keys if ("ок." in k.lower() or "окон" in k.lower()) and "план" in k.lower()),
            None,
        )
        etap_key  = next((k for k in sample_keys if k.lower().strip() == "этап"), None)

        if not title_key:
            logger.warning(f"Column 'Задача' not found in '{sheet_name}' — skipping task creation")
            return [], {}

        # Resolve zadach list info for writing Bitrix Task ID back to list elements
        zadach_list_id = int(zadach_list_info["id"]) if zadach_list_info else None
        zadach_iblock = zadach_list_info.get("iblock_code", "") if zadach_list_info else ""
        btask_id_prop = (
            zadach_list_info.get("extra_field_ids", {}).get("f_ext_btask_id")
            if zadach_list_info else None
        )
        element_info_map: Dict[tuple[str, str], List[Dict[str, Any]]] = (
            zadach_list_info.get("element_info_map", {}) if zadach_list_info else {}
        )

        # Ensure the UF_ETAP custom field exists on tasks (creates it once, ignores if already exists)
        await tasks.ensure_uf_etap_field(self.client)

        logger.info(f"Creating tasks from sheet: {sheet_name}")

        def _to_iso_date(val: Any) -> Optional[str]:
            """Convert date value to ISO YYYY-MM-DD string."""
            if val is None:
                return None
            if hasattr(val, "date"):
                return val.date().isoformat()
            s = str(val).strip()
            # Handle DD.MM.YYYY format from Excel string cells
            if len(s) == 10 and s[2] == "." and s[5] == ".":
                try:
                    return datetime.strptime(s, "%d.%m.%Y").date().isoformat()
                except ValueError:
                    pass
            return s or None

        task_ids = []
        # Maps (etap.lower(), zadacha.lower()) → bitrix_task_id for subtask creation
        task_id_map: Dict[tuple, int] = {}
        for row_idx, row_data in enumerate(rows, start=1):
            try:
                task_title = str(row_data.get(title_key) or "").strip()
                if not task_title:
                    continue

                etap_val = str(row_data.get(etap_key, "")).strip() if etap_key else ""
                deadline = _to_iso_date(row_data.get(end_key) if end_key else None)
                start_date_plan = _to_iso_date(row_data.get(start_key) if start_key else None)

                description = task_title
                if etap_val:
                    description = f"Этап: {etap_val}\n{description}"

                task_id = await tasks.create_task(
                    self.client,
                    title=task_title,
                    description=description,
                    deadline=deadline,
                    start_date_plan=start_date_plan,
                    end_date_plan=deadline,
                    responsible_id=1,
                    group_id=project_id,
                    uf_fields={"UF_ETAP": etap_val} if etap_val else None,
                )

                task_ids.append(task_id)
                task_id_map[(etap_val.lower(), task_title.lower())] = task_id
                logger.info(f"✓ Task {row_idx}: [{etap_val}] {task_title} (ID: {task_id})")

                # Write Bitrix task ID back into the "2. Этапы и задачи" list element.
                # Must pass NAME + ALL existing properties — Bitrix24 lists.element.update
                # REPLACES the property set, so omitted properties get wiped.
                map_key = (etap_val.lower(), task_title.lower())
                if zadach_list_id and btask_id_prop and map_key in element_info_map and element_info_map[map_key]:
                    info = element_info_map[map_key].pop(0)
                    elem_id = info["id"]
                    merged_values = dict(info["field_values"])
                    merged_values[btask_id_prop] = task_id
                    try:
                        await lists.update_element(
                            self.client,
                            list_id=zadach_list_id,
                            iblock_code=zadach_iblock,
                            group_id=project_id,
                            element_id=elem_id,
                            field_values=merged_values,
                            name=task_title,
                        )
                        logger.info(f"  → Linked element {elem_id} → task {task_id}")
                    except ValueError as link_err:
                        logger.warning(f"Failed to link task ID for '{task_title}': {link_err}")

            except ValueError as e:
                logger.error(f"Failed to create task from row {row_idx}: {e}")
                continue

        logger.info(f"✓ Created {len(task_ids)} tasks")
        return task_ids, task_id_map

    @staticmethod
    def _infer_field_type(header: str, sample_value: Any = None) -> str:
        """
        Infer Bitrix24 field type from column header and optional sample value.

        Priority: header keyword match → data type of sample_value → fallback S.

        Returns: S (string), N (number), S:Date (date)
        Note: S:Money is not used — all monetary fields use N for simplicity.
        """
        header_lower = header.lower()

        if any(kw in header_lower for kw in ["дата", "date"]):
            return "S:Date"
        if any(kw in header_lower for kw in [
            "кол-во", "объём", "количество", "qty", "count",
            "готовность", "процент", "чел-час", "человек",
            "сумма", "стоимость", "фот", "ставка", "цена",
            "price", "cost", "sum", "отклонение", "остаток",
        ]):
            return "N"

        # Data-driven fallback: use the actual value type
        if sample_value is not None:
            if isinstance(sample_value, (int, float)):
                return "N"
            if hasattr(sample_value, "isoformat"):
                return "S:Date"

        return "S"


async def main(file_path: str, custom_name: str | None = None) -> None:
    """Main entry point for CLI usage."""
    settings.validate()

    async with BitrixClient() as client:
        importer = ExcelImporter(client)
        result = await importer.import_file(file_path, custom_name=custom_name)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import Excel project plan into Bitrix24.")
    parser.add_argument("file", help="Path to Excel file (.xlsx)")
    parser.add_argument("--name", dest="custom_name", default=None,
                        help="Custom project name (overrides filename)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    asyncio.run(main(args.file, custom_name=args.custom_name))
