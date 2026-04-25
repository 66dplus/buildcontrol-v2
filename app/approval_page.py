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

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from bitrix.client import BitrixClient
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
    format_price_deviation,
    list_pending_across_projects,
    material_context,
    resolve_request,
    verify_token,
)

SOURCE_WIDGET = "widget"

logger = logging.getLogger(__name__)

router = APIRouter()


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _status_badge(status: str) -> str:
    color = {STATUS_PENDING: "#f39c12", STATUS_APPROVED: "#27ae60", STATUS_REJECTED: "#c0392b"}.get(status, "#7f8c8d")
    return f'<span style="background:{color};color:#fff;padding:3px 10px;border-radius:12px;font-size:13px;">{_esc(status)}</span>'


async def _resolve_request_payload(request_id: int) -> Optional[Dict[str, Any]]:
    """Locate the request across projects and gather all data needed to render the page."""
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
    return {
        "project_id": project_id,
        "request": decoded,
        "context": ctx,
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

    async with BitrixClient() as client:
        located = await find_request_in_any_project(client, request_id)
        if not located:
            raise HTTPException(status_code=404, detail="Request not found")
        project_id, *_ = located
        await resolve_request(
            client, project_id, request_id,
            decision=decision, actor=actor_name, source=SOURCE_PAGE, comment=comment,
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
    price_plan = ctx.get("price_plan")
    for it in req.get("items", []):
        sev = format_price_deviation(
            float(it.get("price") or 0),
            float(price_plan or 0),
            float(it.get("qty") or 0),
        )
        severities.append({
            "material_name": it.get("material_name", ""),
            "qty": float(it.get("qty") or 0),
            "unit": it.get("unit") or ctx.get("unit") or "",
            "price": float(it.get("price") or 0),
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
    decision: str = Form(...),
    comment: str = Form(default=""),
) -> JSONResponse:
    """
    Apply a decision from the Bitrix widget. ``actor`` is hardcoded to
    "Согласующий" (user_id = 1) until BX24.callMethod('user.current') is wired in.
    """
    if decision not in (DECISION_APPROVE, DECISION_REJECT, DECISION_COMMENT):
        raise HTTPException(status_code=400, detail=f"Unknown decision: {decision}")

    async with BitrixClient() as client:
        located = await find_request_in_any_project(client, request_id)
        if not located:
            raise HTTPException(status_code=404, detail="Request not found")
        project_id, *_ = located
        result = await resolve_request(
            client, project_id, request_id,
            decision=decision, actor="Согласующий", source=SOURCE_WIDGET, comment=comment,
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
            f'<td style="padding:6px 8px;">{_esc(it.get("material_name", ""))}</td>'
            f'<td style="padding:6px 8px; text-align:right;">{qty} {_esc(unit)}</td>'
            f'<td style="padding:6px 8px; text-align:right;">{price:.2f} ₽</td>'
            f'<td style="padding:6px 8px; text-align:right;">{total:.2f} ₽</td>'
            f'</tr>'
        )

    file_block = ""
    if req.get("file_url"):
        file_block = f'<p>📎 <a href="{_esc(req["file_url"])}" target="_blank">Коммерческое предложение</a></p>'

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
            bg_by_sev = {
                "ok": "#eafaf1", "low": "#fef9e7",
                "medium": "#fef5e7", "high": "#fdedec", "critical": "#fadbd8",
            }
            bd_by_sev = {
                "ok": "#a9dfbf", "low": "#f7dc6f",
                "medium": "#f5b041", "high": "#e74c3c", "critical": "#922b21",
            }
            bg = bg_by_sev.get(sev["severity"], "#ecf0f1")
            bd = bd_by_sev.get(sev["severity"], "#bdc3c7")
            header_html = (
                f'<div style="font-weight:700;font-size:14px;margin-bottom:4px;">{_esc(sev["header"])}</div>'
                if sev["header"] else ""
            )
            severity_banner = (
                f'<div style="background:{bg};border-left:4px solid {bd};padding:10px 12px;'
                f'border-radius:6px;margin:10px 0;font-size:13px;line-height:1.5;">'
                f'<div style="font-size:18px;line-height:1;margin-bottom:4px;">{sev["emoji"]}</div>'
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
        f'<ul style="list-style:none;padding:0;margin:8px 0;line-height:1.7;">{"".join(context_block)}</ul>'
        if context_block else ""
    )

    buyer_comment_html = ""
    if req.get("comment"):
        buyer_comment_html = (
            f'<div style="background:#eaf4fb;border-left:4px solid #2980b9;'
            f'padding:10px 12px;border-radius:6px;margin:10px 0;font-size:13px;">'
            f'<b>💬 Комментарий закупщика:</b><br>{_esc(req["comment"])}</div>'
        )

    is_pending = req.get("status") == STATUS_PENDING
    actions_html = ""
    if is_pending:
        actions_html = f"""
<form method="POST" action="/approval/{req["id"]}/decide" style="margin-top:18px;">
  <input type="hidden" name="token" value="{_esc(token)}">
  <label style="display:block;margin-bottom:6px;font-weight:500;">Комментарий (необязательно)</label>
  <textarea name="comment" rows="3"
            style="width:100%;padding:8px;border:1px solid #ddd;border-radius:6px;margin-bottom:12px;"></textarea>
  <div style="display:flex;gap:8px;flex-wrap:wrap;">
    <button type="submit" name="decision" value="approve"
            style="flex:1;min-width:140px;padding:12px;background:#27ae60;color:#fff;border:0;border-radius:6px;font-size:15px;cursor:pointer;">
      ✅ Подтвердить
    </button>
    <button type="submit" name="decision" value="reject"
            style="flex:1;min-width:140px;padding:12px;background:#c0392b;color:#fff;border:0;border-radius:6px;font-size:15px;cursor:pointer;">
      ❌ Отклонить
    </button>
    <button type="submit" name="decision" value="comment"
            style="flex:1;min-width:140px;padding:12px;background:#7f8c8d;color:#fff;border:0;border-radius:6px;font-size:15px;cursor:pointer;">
      💬 Только комментарий
    </button>
  </div>
</form>
"""
    else:
        actions_html = (
            f'<div style="margin-top:18px;padding:14px;background:#ecf0f1;border-radius:8px;text-align:center;">'
            f'Заявка уже обработана: {_status_badge(req["status"])}</div>'
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
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          max-width: 720px; margin: 0 auto; padding: 16px; color:#2c3e50; background:#f7f9fb; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  .meta {{ color:#7f8c8d; font-size:13px; margin-bottom: 14px; }}
  .card {{ background:#fff; border-radius: 10px; padding: 16px; margin-bottom: 14px;
           box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  table {{ width:100%; border-collapse: collapse; font-size: 14px; }}
  thead th {{ text-align:left; background:#ecf0f1; padding: 6px 8px; font-weight:500; }}
  tbody tr:nth-child(odd) {{ background:#fafbfc; }}
  .total-row {{ font-weight:600; }}
</style>
</head>
<body>
  <h1>Заявка №{req["no"]} {_status_badge(req["status"])}</h1>
  <div class="meta">
    {_esc(req.get("date") or "")} · автор: {_esc(req.get("author") or "—")}
    · этап: {_esc(req.get("etap") or "—")} · задача: {_esc(req.get("zadacha") or "—")}
  </div>

  <div class="card">
    <h2 style="font-size:15px;margin:0 0 8px 0;">Позиции</h2>
    <table>
      <thead><tr>
        <th>Материал</th><th style="text-align:right;">Кол-во</th>
        <th style="text-align:right;">Цена ед.</th><th style="text-align:right;">Сумма</th>
      </tr></thead>
      <tbody>{"".join(items_rows)}</tbody>
      <tfoot><tr class="total-row">
        <td colspan="3" style="padding:8px;text-align:right;">Итого:</td>
        <td style="padding:8px;text-align:right;">{total_sum:.2f} ₽</td>
      </tr></tfoot>
    </table>
    {file_block}
    {severity_banner}
    {buyer_comment_html}
    {context_html}
  </div>

  <div class="card">
    <h2 style="font-size:15px;margin:0 0 8px 0;">Решение</h2>
    {actions_html}
  </div>

  {poll_script}
</body>
</html>
"""
