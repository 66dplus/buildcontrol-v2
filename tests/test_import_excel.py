"""Tests for the pure helpers in scripts.import_excel.

The ExcelImporter orchestration class requires a heavy Bitrix mock and is
covered by integration smoke. These tests target the silent-corruption
hotspots flagged in the audit:

- ``_infer_field_type`` — wrong type → wrong Bitrix field, data ends up in
  the wrong column or rejected silently.
- ``_apply_formula_fallbacks`` — Google Sheets / LibreOffice files lose
  cached formula values; the importer must recompute them.
- ``_deduplicate_labor_rows`` — multiple rows for one specialty must merge.
- ``_NAME_COLUMN_KEYWORDS`` ordering — "подзадач" must come before "задач"
  because "подзадачи" contains "задач".
"""

from __future__ import annotations

import datetime as _dt

from scripts.import_excel import (
    ExcelImporter,
    _apply_formula_fallbacks,
    _deduplicate_labor_rows,
)


# ---------------------------------------------------------------------------
# _infer_field_type
# ---------------------------------------------------------------------------


def test_infer_field_type_date_columns_become_S_Date() -> None:
    # The "2. Этапы и задачи" sheet has Дата нач. план, Дата ок. план,
    # Дата нач. факт, Дата ок. факт. All four MUST resolve to S:Date so the
    # cascade and stage-progress writes can compare dates correctly.
    for header in ["Дата нач. план", "Дата ок. план", "Дата нач. факт", "Дата ок. факт"]:
        assert ExcelImporter._infer_field_type(header) == "S:Date", header


def test_infer_field_type_completion_pct_is_N() -> None:
    # Готовн. план, % and Готовн. факт, % must be N — the cascade writes
    # numeric percentages into them. Returning S would silently coerce or fail.
    assert ExcelImporter._infer_field_type("Готовн. план, %") == "N"
    assert ExcelImporter._infer_field_type("Готовн. факт, %") == "N"


def test_infer_field_type_money_columns_are_N() -> None:
    # All ₽ / cost / payroll columns are N (S:Money is intentionally not used).
    for header in [
        "Стоим. план, ₽",
        "Стоим. факт, ₽",
        "ФОТ план, ₽",
        "ФОТ факт, ₽",
        "Бюджет факт, ₽",
        "Цена ед. план, ₽",
        "Ставка, ₽/час",
    ]:
        assert ExcelImporter._infer_field_type(header) == "N", header


def test_infer_field_type_quantity_columns_are_N() -> None:
    for header in [
        "Объём план", "Объём куплено", "Объём израсходовано",
        "Остаток на складе", "Ч-часов план", "Часов факт",
    ]:
        assert ExcelImporter._infer_field_type(header) == "N", header


def test_infer_field_type_falls_back_to_string_for_unknown() -> None:
    # Plain text-y columns with no keyword and no sample → S.
    assert ExcelImporter._infer_field_type("Этап") == "S"
    assert ExcelImporter._infer_field_type("Задача") == "S"
    assert ExcelImporter._infer_field_type("Наименование") == "S"


def test_infer_field_type_uses_sample_value_when_header_ambiguous() -> None:
    # No keyword match → sample value drives type.
    assert ExcelImporter._infer_field_type("Custom", sample_value=42) == "N"
    assert ExcelImporter._infer_field_type("Custom", sample_value=3.14) == "N"
    assert ExcelImporter._infer_field_type("Custom", sample_value=_dt.date(2026, 1, 1)) == "S:Date"
    assert ExcelImporter._infer_field_type("Custom", sample_value="text") == "S"
    assert ExcelImporter._infer_field_type("Custom", sample_value=None) == "S"


def test_infer_field_type_bitrix_task_id_is_N() -> None:
    # Bitrix Task ID is a numeric reference, must be N.
    assert ExcelImporter._infer_field_type("Bitrix Task ID") == "S"
    # Note: header lacks a numeric keyword. If sample is numeric, we should still get N.
    assert ExcelImporter._infer_field_type("Bitrix Task ID", sample_value=12345) == "N"


# ---------------------------------------------------------------------------
# _NAME_COLUMN_KEYWORDS — ordering matters
# ---------------------------------------------------------------------------


def test_name_column_keywords_подзадач_before_задач() -> None:
    # "подзадачи" contains "задач" — if "задач" is checked first the
    # subtask sheet would resolve to the wrong NAME column. Iteration order
    # of the dict is the lookup order in _create_lists.
    keys = list(ExcelImporter._NAME_COLUMN_KEYWORDS.keys())
    assert keys.index("подзадач") < keys.index("задач")


# ---------------------------------------------------------------------------
# _apply_formula_fallbacks
# ---------------------------------------------------------------------------


def test_formula_fallback_materials_cost_plan() -> None:
    row = {
        "Объём план": 10.0,
        "Цена ед. план, ₽": 50.0,
        "Стоим. план, ₽": None,  # missing — must be filled in
    }
    _apply_formula_fallbacks("3. Материалы", row)
    assert row["Стоим. план, ₽"] == 500.0


def test_formula_fallback_does_not_overwrite_excel_cached_value() -> None:
    # If Excel cached the formula result, importer must NOT overwrite it.
    row = {
        "Объём план": 10.0,
        "Цена ед. план, ₽": 50.0,
        "Стоим. план, ₽": 999.99,  # cached — preserve as-is
    }
    _apply_formula_fallbacks("3. Материалы", row)
    assert row["Стоим. план, ₽"] == 999.99


def test_formula_fallback_labor_payroll() -> None:
    row = {
        "Ч-часов план": 8.0,
        "Ставка, ₽/час": 200.0,
        "ФОТ план, ₽": None,
    }
    _apply_formula_fallbacks("4. Трудозатраты", row)
    assert row["ФОТ план, ₽"] == 1600.0


def test_formula_fallback_equipment_total() -> None:
    row = {
        "Часов план": 5.0,
        "Цена, ₽/час": 1000.0,
        "Итого план, ₽": None,
    }
    _apply_formula_fallbacks("5. Техника", row)
    assert row["Итого план, ₽"] == 5000.0


def test_formula_fallback_budget_total() -> None:
    # 1. Бюджет: Итого план = Материалы + ФОТ + Техника
    row = {
        "Материалы план, ₽": 100.0,
        "ФОТ план, ₽": 200.0,
        "Техника план, ₽": 50.0,
        "Итого план, ₽": None,
    }
    _apply_formula_fallbacks("1. Бюджет", row)
    assert row["Итого план, ₽"] == 350.0


def test_formula_fallback_skips_when_inputs_missing() -> None:
    # If ANY input is missing, the formula is not computed (None stays).
    row = {
        "Объём план": 10.0,
        "Цена ед. план, ₽": None,  # missing
        "Стоим. план, ₽": None,
    }
    _apply_formula_fallbacks("3. Материалы", row)
    assert row["Стоим. план, ₽"] is None


# ---------------------------------------------------------------------------
# _deduplicate_labor_rows
# ---------------------------------------------------------------------------


def test_deduplicate_labor_sums_numerics_for_same_specialty() -> None:
    rows = [
        {"Этап": "Ф1", "Задача": "З1", "Специальность": "Каменщик", "Ч-часов план": 8.0, "ФОТ план": 1600.0},
        {"Этап": "Ф1", "Задача": "З1", "Специальность": "Каменщик", "Ч-часов план": 4.0, "ФОТ план": 800.0},
    ]
    out = _deduplicate_labor_rows(rows)
    assert len(out) == 1
    assert out[0]["Ч-часов план"] == 12.0
    assert out[0]["ФОТ план"] == 2400.0


def test_deduplicate_labor_keeps_distinct_specialties() -> None:
    rows = [
        {"Этап": "Ф1", "Задача": "З1", "Специальность": "Каменщик", "Ч-часов план": 8.0},
        {"Этап": "Ф1", "Задача": "З1", "Специальность": "Бетонщик", "Ч-часов план": 8.0},
    ]
    out = _deduplicate_labor_rows(rows)
    assert len(out) == 2


def test_deduplicate_labor_passes_unique_rows_through() -> None:
    rows = [
        {"Этап": "Ф1", "Задача": "З1", "Специальность": "Каменщик", "Ч-часов план": 8.0},
    ]
    out = _deduplicate_labor_rows(rows)
    assert out == rows
