"""
Approval page — single source of truth for approve/reject/comment actions
on a procurement request.

Routes:
    GET  /approval/{id}            — render page (HTML)
    GET  /approval/{id}/state      — JSON snapshot for live polling
    POST /approval/{id}/decide     — apply decision (form submit)
"""

from __future__ import annotations

import html
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from bitrix.client import BitrixClient
from app._ui_styles import BASE_CSS, FONT_LINKS
from app.purchase_requests import (
    DECISION_APPROVE,
    DECISION_COMMENT,
    DECISION_REJECT,
    SOURCE_PAGE,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    approval_url,
    find_request_in_any_project,
    find_request_sqlite,
    format_price_deviation,
    list_pending_across_projects,
    material_context,
    materials_plan_index_sqlite,
    mirror_decision_to_bitrix,
    resolve_request,
    resolve_request_sqlite_first,
    verify_token,
)

SOURCE_WIDGET = "widget"

logger = logging.getLogger(__name__)

router = APIRouter()


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _status_badge(status: str) -> str:
    variant = {
        STATUS_PENDING: "warn",
        STATUS_APPROVED: "success",
        STATUS_REJECTED: "danger",
    }.get(status, "neutral")
    return f'<span class="bc-pill bc-pill--{variant}">{_esc(status)}</span>'


async def _resolve_request_payload(request_id: int) -> Optional[Dict[str, Any]]:
    """Locate the request (SQLite first, Bitrix fallback) and gather rendering data."""
    decoded = await find_request_sqlite(request_id)
    if decoded:
        project_id = decoded["project_id"]
        primary = decoded["items"][0] if decoded["items"] else {"material_name": "", "qty": 0, "price": 0}
        plan_index = await materials_plan_index_sqlite(project_id)
        async with BitrixClient() as client:
            ctx = await material_context(
                client, project_id, primary.get("material_name", ""),
                float(primary.get("qty") or 0), float(primary.get("price") or 0),
            )
        return {
            "project_id": project_id,
            "request": decoded,
            "context": ctx,
            "plan_index": plan_index,
        }

    # Fallback: Bitrix fan-out (for requests not yet in SQLite)
    async with BitrixClient() as client:
        located = await find_request_in_any_project(client, request_id)
        if not located:
            return None
        project_id, list_info, raw_row, decoded = located
        primary = decoded["items"][0] if decoded["items"] else {"material_name": "", "qty": 0, "price": 0}
        ctx = await material_context(
            client, project_id, primary.get("material_name", ""),
            float(primary.get("qty") or 0), float(primary.get("price") or 0),
        )
        from app.purchase_requests import materials_plan_index
        plan_index = await materials_plan_index(client, project_id)
    return {
        "project_id": project_id,
        "request": decoded,
        "context": ctx,
        "plan_index": plan_index,
    }


@router.get("/approval/{request_id}", response_class=HTMLResponse)
async def get_approval_page(request_id: int, token: str = Query(default="")) -> HTMLResponse:
    if not verify_token(request_id, token):
        raise HTTPException(status_code=403, detail="Invalid or missing token")
    payload = await _resolve_request_payload(request_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Request not found")
    html_body = _render_html(payload, token)
    return HTMLResponse(content=html_body)


@router.get("/approval/{request_id}/state")
async def get_approval_state(request_id: int, token: str = Query(default="")) -> JSONResponse:
    if not verify_token(request_id, token):
        raise HTTPException(status_code=403, detail="Invalid or missing token")
    payload = await _resolve_request_payload(request_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Request not found")
    return JSONResponse(content={
        "status": payload["request"]["status"],
        "history": payload["request"]["history"],
    })


@router.post("/approval/{request_id}/decide")
async def post_approval_decide(
    request_id: int,
    request: Request,
    background: BackgroundTasks,
    token: str = Form(...),
    decision: str = Form(...),
    actor: str = Form(default=""),
    comment: str = Form(default=""),
) -> RedirectResponse:
    if not verify_token(request_id, token):
        raise HTTPException(status_code=403, detail="Invalid or missing token")
    if decision not in (DECISION_APPROVE, DECISION_REJECT, DECISION_COMMENT):
        raise HTTPException(status_code=400, detail=f"Unknown decision: {decision}")

    actor_name = (actor or "").strip() or "Согласующий"

    result = await resolve_request_sqlite_first(
        request_id,
        decision=decision, actor=actor_name, source=SOURCE_PAGE, comment=comment,
    )
    project_id = result.get("project_id")

    if project_id is None:
        # SQLite has no record; fall back to Bitrix fan-out (legacy path)
        async with BitrixClient() as client:
            located = await find_request_in_any_project(client, request_id)
            if not located:
                raise HTTPException(status_code=404, detail="Request not found")
            project_id, *_ = located
            await resolve_request(
                client, project_id, request_id,
                decision=decision, actor=actor_name, source=SOURCE_PAGE, comment=comment,
            )
    elif not result.get("already_resolved"):
        background.add_task(
            mirror_decision_to_bitrix,
            request_id, project_id, decision, actor_name, SOURCE_PAGE, comment,
        )

    return RedirectResponse(url=approval_url(request_id), status_code=303)


# ---------------------------------------------------------------------------
# Widget API — approver works inside the Bitrix iframe (no token needed; the
# Bitrix session itself is the auth boundary).  These endpoints power the new
# "Согласование" tab in /bitrix/widget.
# ---------------------------------------------------------------------------


@router.get("/api/purchase-requests/pending")
async def api_pending_requests() -> JSONResponse:
    """Return all pending purchase requests across every project."""
    async with BitrixClient() as client:
        items = await list_pending_across_projects(client)
    return JSONResponse(content=items)


@router.get("/api/purchase-requests/{request_id}")
async def api_request_detail(request_id: int) -> JSONResponse:
    """Return full payload for a single request, including price-deviation severity."""
    payload = await _resolve_request_payload(request_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Request not found")
    req = payload["request"]
    ctx = payload["context"]

    severities: list[Dict[str, Any]] = []
    plan_index: Dict[str, Dict[str, Any]] = payload.get("plan_index") or {}
    fallback_price_plan = ctx.get("price_plan")
    for it in req.get("items", []):
        mat_name = it.get("material_name", "") or ""
        entry = plan_index.get(mat_name.lower(), {})
        item_price_plan = entry.get("price_plan")
        if item_price_plan is None:
            item_price_plan = fallback_price_plan
        sev = format_price_deviation(
            float(it.get("price") or 0),
            float(item_price_plan or 0),
            float(it.get("qty") or 0),
        )
        severities.append({
            "material_name": mat_name,
            "qty": float(it.get("qty") or 0),
            "unit": it.get("unit") or entry.get("unit") or ctx.get("unit") or "",
            "price": float(it.get("price") or 0),
            "price_plan": item_price_plan,
            "total": float(it.get("total") or (float(it.get("qty") or 0) * float(it.get("price") or 0))),
            "severity": sev,
        })

    return JSONResponse(content={
        "request_id": req["id"],
        "request_no": req["no"],
        "project_id": payload["project_id"],
        "date": req["date"],
        "author": req["author"],
        "etap": req["etap"],
        "zadacha": req["zadacha"],
        "status": req["status"],
        "comment": req["comment"],
        "file_url": req["file_url"],
        "items": severities,
        "context": {
            "price_plan": ctx.get("price_plan"),
            "stock_now": ctx.get("stock_now"),
            "active_projects": ctx.get("active_projects"),
            "future_projects": ctx.get("future_projects"),
            "over_plan": ctx.get("over_plan"),
        },
    })


@router.post("/api/purchase-requests/{request_id}/decide")
async def api_request_decide(
    request_id: int,
    background: BackgroundTasks,
    decision: str = Form(...),
    comment: str = Form(default=""),
) -> JSONResponse:
    """
    Apply a decision from the Bitrix widget. ``actor`` is hardcoded to
    "Согласующий" (user_id = 1) until BX24.callMethod('user.current') is wired in.
    """
    if decision not in (DECISION_APPROVE, DECISION_REJECT, DECISION_COMMENT):
        raise HTTPException(status_code=400, detail=f"Unknown decision: {decision}")

    result = await resolve_request_sqlite_first(
        request_id,
        decision=decision, actor="Согласующий", source=SOURCE_WIDGET, comment=comment,
    )
    project_id = result.get("project_id")

    if project_id is None:
        async with BitrixClient() as client:
            located = await find_request_in_any_project(client, request_id)
            if not located:
                raise HTTPException(status_code=404, detail="Request not found")
            project_id, *_ = located
            result = await resolve_request(
                client, project_id, request_id,
                decision=decision, actor="Согласующий", source=SOURCE_WIDGET, comment=comment,
            )
    elif not result.get("already_resolved"):
        background.add_task(
            mirror_decision_to_bitrix,
            request_id, project_id, decision, "Согласующий", SOURCE_WIDGET, comment,
        )

    return JSONResponse(content={
        "success": True,
        "status": result["status"],
        "already_resolved": result.get("already_resolved", False),
    })


def _render_html(payload: Dict[str, Any], token: str) -> str:
    req = payload["request"]
    ctx = payload["context"]
    items = req.get("items", [])

    items_rows: list[str] = []
    total_sum = 0.0
    for it in items:
        qty = float(it.get("qty") or 0)
        price = float(it.get("price") or 0)
        unit = it.get("unit") or ctx.get("unit") or ""
        total = float(it.get("total") or (qty * price))
        total_sum += total
        items_rows.append(
            f'<tr>'
            f'<td data-label="Материал">{_esc(it.get("material_name", ""))}</td>'
            f'<td data-label="Кол-во" class="num">{qty} {_esc(unit)}</td>'
            f'<td data-label="Цена ед." class="num">{price:.2f} ₽</td>'
            f'<td data-label="Сумма" class="num">{total:.2f} ₽</td>'
            f'</tr>'
        )

    file_block = ""
    if req.get("file_url"):
        file_block = (
            f'<p style="margin-top:12px;">📎 '
            f'<a href="{_esc(req["file_url"])}" target="_blank">Коммерческое предложение</a></p>'
        )

    severity_banner = ""
    price_plan = ctx.get("price_plan")
    if price_plan and items:
        first = items[0]
        sev = format_price_deviation(
            float(first.get("price") or 0),
            float(price_plan or 0),
            float(first.get("qty") or 0),
        )
        if sev["severity"] not in ("none",):
            variant_by_sev = {
                "ok": "success",
                "low": "warn",
                "medium": "warn",
                "high": "danger",
                "critical": "danger",
            }
            variant = variant_by_sev.get(sev["severity"], "info")
            header_html = (
                f'<div class="bc-banner__title">{_esc(sev["header"])}</div>'
                if sev["header"] else ""
            )
            severity_banner = (
                f'<div class="bc-banner bc-banner--{variant}">'
                f'<span class="bc-banner__icon">{sev["emoji"]}</span>'
                f'{header_html}'
                f'<div>{_esc(sev["body"])}</div>'
                f'</div>'
            )

    context_block: list[str] = []
    if ctx.get("over_plan"):
        context_block.append('<li>⚠ Объём превышает план для этого материала</li>')
    if ctx.get("stock_now") is not None:
        context_block.append(f'<li>📦 Остаток на складе сейчас: {ctx["stock_now"]}</li>')
    if ctx.get("active_projects") is not None:
        context_block.append(f'<li>🏗 Активных проектов с этим материалом: {ctx["active_projects"]}</li>')
    if ctx.get("future_projects") is not None:
        context_block.append(f'<li>🗓 Запланировано в будущих проектах: {ctx["future_projects"]}</li>')
    context_html = (
        f'<ul class="bc-context-list">{"".join(context_block)}</ul>'
        if context_block else ""
    )

    buyer_comment_html = ""
    if req.get("comment"):
        buyer_comment_html = (
            f'<div class="bc-banner bc-banner--info" style="margin-top:12px;">'
            f'<div class="bc-banner__title">💬 Комментарий закупщика</div>'
            f'<div>{_esc(req["comment"])}</div>'
            f'</div>'
        )

    is_pending = req.get("status") == STATUS_PENDING
    if is_pending:
        actions_html = f"""
<form method="POST" action="/approval/{req["id"]}/decide" class="bc-decision-form" id="bcDecideForm">
  <input type="hidden" name="token" value="{_esc(token)}">
  <div class="form-group">
    <label>Комментарий (необязательно)</label>
    <textarea name="comment" rows="3"></textarea>
  </div>
  <div class="bc-btn-row">
    <button type="submit" name="decision" value="approve" class="bc-btn bc-btn--success">
      ✅ Подтвердить
    </button>
    <button type="submit" name="decision" value="reject" class="bc-btn bc-btn--danger">
      ❌ Отклонить
    </button>
    <button type="submit" name="decision" value="comment" class="bc-btn bc-btn--secondary">
      💬 Только комментарий
    </button>
  </div>
</form>
<script>
(function() {{
  var form = document.getElementById('bcDecideForm');
  if (!form) return;
  form.addEventListener('submit', function(e) {{
    if (form.dataset.submitted === '1') {{ e.preventDefault(); return; }}
    form.dataset.submitted = '1';
    form.querySelectorAll('button').forEach(function(b) {{ b.disabled = true; }});
    setTimeout(function() {{
      form.dataset.submitted = '';
      form.querySelectorAll('button').forEach(function(b) {{ b.disabled = false; }});
    }}, 5000);
  }});
}})();
</script>
"""
    else:
        actions_html = (
            f'<div class="bc-resolved-note">'
            f'Заявка уже обработана: {_status_badge(req["status"])}'
            f'</div>'
        )

    poll_script = f"""
<script>
async function poll() {{
  try {{
    const r = await fetch('/approval/{req["id"]}/state?token={_esc(token)}');
    if (!r.ok) return;
    const data = await r.json();
    if (data.status !== '{_esc(req["status"])}') location.reload();
  }} catch (_) {{}}
}}
setInterval(poll, 10000);
</script>
"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Заявка №{req["no"]} — Согласование</title>
{FONT_LINKS}
{BASE_CSS}
<style>
  .bc-context-list {{ list-style: none; padding: 0; margin: 12px 0 0; line-height: 1.7; }}
  .bc-context-list li {{ font-size: 13px; color: var(--bc-ink); }}
  .bc-decision-form {{ margin-top: 4px; }}
  .bc-resolved-note {{
    margin-top: 4px; padding: 16px;
    background: var(--bc-surface-alt);
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-radius-card);
    text-align: center;
    color: var(--bc-ink-muted);
  }}
  body {{ background: var(--bc-bg); }}
</style>
</head>
<body>
<div class="bc-page bc-stack">
  <div>
    <h1>Заявка №{req["no"]} {_status_badge(req["status"])}</h1>
    <div class="bc-meta">
      {_esc(req.get("date") or "")} · автор: {_esc(req.get("author") or "—")}
      · этап: {_esc(req.get("etap") or "—")} · задача: {_esc(req.get("zadacha") or "—")}
    </div>
  </div>

  <div class="bc-card">
    <div class="bc-card-header"><h2>Позиции</h2></div>
    <table class="bc-table bc-table--responsive">
      <thead><tr>
        <th>Материал</th>
        <th class="num">Кол-во</th>
        <th class="num">Цена ед.</th>
        <th class="num">Сумма</th>
      </tr></thead>
      <tbody>{"".join(items_rows)}</tbody>
      <tfoot><tr>
        <td colspan="3" class="num" data-label="Итого">Итого:</td>
        <td class="num" data-label="Сумма">{total_sum:.2f} ₽</td>
      </tr></tfoot>
    </table>
    {file_block}
    {severity_banner}
    {buyer_comment_html}
    {context_html}
  </div>

  <div class="bc-card">
    <div class="bc-card-header"><h2>Решение</h2></div>
    {actions_html}
  </div>
</div>
{poll_script}
</body>
</html>
"""
