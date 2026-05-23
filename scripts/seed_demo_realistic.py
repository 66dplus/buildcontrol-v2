"""
Seed realistic demo data for video recording.

What this does (idempotent — safe to run multiple times):

1. Renames three existing projects to realistic Russian construction names and
   scales their plan/actual values so they look distinct on the dashboard:

      #34 → ЖК «Северный квартал», корпус 4   (крупная новостройка, в работе)
      #36 → Коттеджный посёлок «Сосновый бор»  (малая стройка, ранняя стадия)
      #38 → Реконструкция БЦ «Меридиан»        (среднеценовой ремонт, ~50% готов)

2. Archives the other demo projects (#40, #9001) so the dashboard shows exactly
   three active sites.

3. Generates a 1-page commercial-proposal PDF at
   ``frontend/public/demo-proposal.pdf`` (served at ``/demo-proposal.pdf``).

4. Inserts a pending purchase request on the БЦ «Меридиан» project pointing
   at that PDF, so the "На согласовании" tab is non-empty on first open.

Run:
    python3 scripts/seed_demo_realistic.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.database import get_db  # noqa: E402


PROJECT_RENAMES = {
    34: "ЖК «Северный квартал», корпус 4",
    36: "Коттеджный посёлок «Сосновый бор»",
    38: "Реконструкция БЦ «Меридиан»",
}

# Multipliers applied to plan/actual columns so the three projects don't look
# like exact copies of one template.
PROJECT_SCALES = {
    # pid: (plan_mult, actual_mult)
    34: (1.00, 1.00),   # leave as-is — already has live fact data
    36: (0.55, 0.05),   # smaller cottage village, just starting
    38: (1.35, 0.55),   # bigger BC renovation, ~half-done
}

PROJECTS_TO_ARCHIVE = (40, 9001)


# ---------------------------------------------------------------------------
# Minimal PDF — hand-built, no external libs.
# ---------------------------------------------------------------------------

def _pdf_string(text: str) -> bytes:
    """Encode a string as a PDF UTF-16BE hex literal (handles Cyrillic)."""
    payload = "FEFF" + text.encode("utf-16-be").hex().upper()
    return f"<{payload}>".encode("ascii")


def build_demo_pdf(out_path: Path) -> None:
    """Build a tiny single-page A4 PDF with a fake commercial proposal."""
    lines = [
        "OOO ТД «Стройпоставка»",
        "ИНН 7728123456 / КПП 772801001",
        "г. Москва, ул. Ленина, 14, оф. 305",
        "тел. +7 (495) 123-45-67",
        "",
        "Коммерческое предложение № КП-2026/0517",
        "от 17 мая 2026 г.",
        "",
        "Объект: Реконструкция БЦ «Меридиан»",
        "",
        "Позиция: Цемент М500 Д0, мешок 50 кг",
        "Количество: 240 мешков",
        "Цена за единицу: 510 руб. (с НДС)",
        "Итого: 122 400 руб.",
        "",
        "Срок поставки: 3 рабочих дня",
        "Условия оплаты: предоплата 50%",
        "",
        "Подпись: ___________  Иванов И.И., менеджер",
    ]

    # Build content stream — Helvetica 12pt with line spacing.
    parts = ["BT", "/F1 12 Tf", "14 TL", "60 770 Td"]
    for line in lines:
        if line:
            parts.append(f"{_pdf_string(line).decode('ascii')} Tj")
        parts.append("T*")
    parts.append("ET")
    stream_body = "\n".join(parts).encode("ascii")

    # We need a font that supports Cyrillic — Type0 with Identity-H + a CIDFont
    # over Helvetica gives us Unicode without embedding a TTF. For a one-page
    # demo, browsers usually substitute a system font for the missing CIDFont.
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    catalog_n = add(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_n = add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    page_n = add(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
    )
    # Font: Type0 with Helvetica + Identity-H — best-effort Cyrillic.
    font_n = add(
        b"<< /Type /Font /Subtype /Type0 /BaseFont /Helvetica "
        b"/Encoding /Identity-H /DescendantFonts [6 0 R] >>"
    )
    content_n = add(
        b"<< /Length " + str(len(stream_body)).encode("ascii") + b" >>\nstream\n"
        + stream_body + b"\nendstream"
    )
    descendant_n = add(
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Helvetica "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        b"/CIDToGIDMap /Identity >>"
    )

    # Assemble the file with xref.
    out = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects)+1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode("ascii")
        + f" /Root {catalog_n} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )

    # Silence unused-var warnings — these are object numbers we may reference.
    _ = (pages_n, page_n, font_n, content_n, descendant_n)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out)
    print(f"  PDF written: {out_path} ({len(out)} bytes)")


# ---------------------------------------------------------------------------
# DB mutations
# ---------------------------------------------------------------------------

PLAN_COLUMNS = {
    "budget_phases": ["materials_plan", "labor_plan", "equipment_plan", "total_plan"],
    "tasks":         ["budget_plan"],
    "materials":     ["price_plan", "qty_plan", "cost_plan"],
    "labor":         ["rate", "hours_plan", "payroll_plan"],
    "equipment_items": ["price_per_hour", "hours_plan", "total_plan"],
}
ACTUAL_COLUMNS = {
    "budget_phases": ["materials_actual", "labor_actual", "equipment_actual", "total_actual"],
    "tasks":         ["budget_actual"],
    "materials":     ["qty_bought", "qty_consumed", "qty_stock", "cost_actual"],
    "labor":         ["hours_actual", "payroll_actual"],
    "equipment_items": ["hours_actual", "total_actual"],
}


async def scale_project(conn, pid: int, plan_mult: float, actual_mult: float) -> None:
    if plan_mult == 1.0 and actual_mult == 1.0:
        return
    for table, cols in PLAN_COLUMNS.items():
        for col in cols:
            await conn.execute(
                f"UPDATE {table} SET {col} = ROUND({col} * ?, 2) WHERE project_id = ?",
                (plan_mult, pid),
            )
    for table, cols in ACTUAL_COLUMNS.items():
        for col in cols:
            await conn.execute(
                f"UPDATE {table} SET {col} = ROUND({col} * ?, 2) WHERE project_id = ?",
                (actual_mult, pid),
            )


async def main() -> None:
    async with get_db() as conn:
        # Idempotency guard: scaling is *not* idempotent. If a prior run already
        # renamed #34 to its realistic name, skip the scale step on subsequent
        # runs so values don't compound.
        async with conn.execute(
            "SELECT name FROM projects WHERE id = 34"
        ) as cur:
            row = await cur.fetchone()
        already_seeded = bool(row) and row[0] == PROJECT_RENAMES[34]

        # 1) Rename + scale 3 demo projects
        for pid, new_name in PROJECT_RENAMES.items():
            await conn.execute(
                "UPDATE projects SET name = ?, is_archived = 0 WHERE id = ?",
                (new_name, pid),
            )
            if not already_seeded:
                plan_m, actual_m = PROJECT_SCALES[pid]
                await scale_project(conn, pid, plan_m, actual_m)
                print(f"  #{pid}: renamed -> {new_name!r}, plan×{plan_m}, actual×{actual_m}")
            else:
                print(f"  #{pid}: rename refreshed (scale skipped — already seeded)")

        # 2) Archive the leftover demo projects and drop their pending requests
        # so the "На согласовании" tab doesn't show stale items.
        for pid in PROJECTS_TO_ARCHIVE:
            await conn.execute(
                "UPDATE projects SET is_archived = 1 WHERE id = ?", (pid,)
            )
            await conn.execute(
                "DELETE FROM purchase_requests "
                "WHERE project_id = ? AND status = 'pending'",
                (pid,),
            )
            print(f"  #{pid}: archived (+ pending requests cleared)")

        await conn.commit()

        # 3) PDF
        pdf_path = ROOT / "frontend" / "public" / "demo-proposal.pdf"
        build_demo_pdf(pdf_path)

        # 4) Pending purchase request on БЦ «Меридиан» (pid=38)
        # Find a real material on that project for the items list.
        async with conn.execute(
            "SELECT phase, task_name, material_name, unit, price_plan "
            "FROM materials WHERE project_id = 38 LIMIT 1"
        ) as cur:
            mat = await cur.fetchone()

        if not mat:
            print("  ! Project #38 has no materials — skipping purchase request seed")
            return

        # Drop any prior demo request so this script stays idempotent.
        await conn.execute(
            "DELETE FROM purchase_requests "
            "WHERE project_id = 38 AND buyer_comment LIKE 'DEMO:%'"
        )

        items = [
            {
                "material_name": "Цемент М500 Д0, мешок 50 кг",
                "qty": 240,
                "unit": "мешок",
                "price": 510,
                "price_plan": 480,
                "total": 240 * 510,
            },
            {
                "material_name": "Песок строительный (просеянный)",
                "qty": 18,
                "unit": "м³",
                "price": 1450,
                "price_plan": 1300,
                "total": 18 * 1450,
            },
            {
                "material_name": "Арматура 12мм А500С",
                "qty": 1.2,
                "unit": "т",
                "price": 62000,
                "price_plan": 58000,
                "total": int(1.2 * 62000),
            },
        ]
        req_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO purchase_requests
                (id, project_id, status, items_json, buyer_comment,
                 proposal_filename, file_url, created_at)
            VALUES (?, 38, 'pending', ?, ?, ?, ?, datetime('now'))
            """,
            (
                req_id,
                json.dumps(items, ensure_ascii=False),
                "DEMO: Цемент + песок + арматура для монолитных работ. "
                "Поставщик ТД «Стройпоставка», предоплата 50%, поставка 3 дня.",
                "kp-stroyposavka-2026-0517.pdf",
                "/demo-proposal.pdf",
            ),
        )
        await conn.commit()
        print(f"  purchase request seeded: id={req_id[:8]}… on project #38")
        _ = mat  # noqa: F841 — sample only

    print("\nDone. Refresh the browser to see the new state.")


if __name__ == "__main__":
    asyncio.run(main())
