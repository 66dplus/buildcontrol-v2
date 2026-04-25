"""
Bitrix24 local app integration.

Routes:
    POST /bitrix/install  — called by Bitrix24 on first app install (or re-open
                            if BX24.installFinish() never completed). Registers
                            LEFT_MENU widget, calls installFinish, shows upload form.
    GET/POST /bitrix/widget — iframe page for the upload form widget.
"""

import logging

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bitrix")

WIDGET_TITLE = "BuildControl"

# BX24.js CDN — the portal-domain path (/bitrix/js/api/rest/bx24/bx24.js)
# returns 404 on cloud Bitrix24; this CDN always works.
BX24_JS_URL = "https://api.bitrix24.com/api/v1/"


# ---------------------------------------------------------------------------
# Install handler
# ---------------------------------------------------------------------------

@router.post("/install", response_class=HTMLResponse)
async def install(request: Request) -> HTMLResponse:
    """
    Called by Bitrix24 when the local app is installed (first time)
    or re-opened if BX24.installFinish() never completed.

    Bitrix24 POSTs form data with AUTH_ID, DOMAIN (query param), status, etc.
    """
    form = await request.form()
    raw = dict(form)

    AUTH_ID = raw.get("AUTH_ID") or raw.get("auth[access_token]") or ""
    status = raw.get("status", "")
    placement = raw.get("PLACEMENT", "")

    DOMAIN = (
        request.query_params.get("DOMAIN")
        or raw.get("DOMAIN")
        or raw.get("auth[domain]")
        or ""
    )
    if not DOMAIN:
        server_endpoint = raw.get("SERVER_ENDPOINT", "")
        if server_endpoint and "oauth.bitrix" not in server_endpoint:
            from urllib.parse import urlparse
            DOMAIN = urlparse(server_endpoint).netloc

    logger.info(
        f"Install called: DOMAIN={DOMAIN} AUTH_ID_present={bool(AUTH_ID)} "
        f"status={status} PLACEMENT={placement}"
    )

    if not AUTH_ID or not DOMAIN:
        logger.warning(f"Install missing fields. Keys: {list(raw.keys())}")
        return HTMLResponse(
            _install_page(success=False, error=f"Missing AUTH_ID or DOMAIN. Keys: {list(raw.keys())}")
        )

    vps_url = settings.vps_url
    base_url = f"https://{DOMAIN}/rest"
    headers = {"Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Unbind any stale LEFT_MENU handler first (e.g. old Cloudflare tunnel
        # URL after tunnel restart). Ignored if nothing is bound.
        try:
            unbind_resp = await client.post(
                f"{base_url}/placement.unbind",
                json={"auth": AUTH_ID, "PLACEMENT": "LEFT_MENU"},
                headers=headers,
            )
            logger.info(f"placement.unbind result: {unbind_resp.json()}")
        except Exception as e:
            logger.warning(f"placement.unbind skipped: {e}")

        bind_payload = {
            "auth": AUTH_ID,
            "PLACEMENT": "LEFT_MENU",
            "HANDLER": f"{vps_url}/bitrix/widget",
            "TITLE": WIDGET_TITLE,
            "LANG_ALL": {
                "ru": {"TITLE": "BuildControl"},
                "en": {"TITLE": "BuildControl"},
            },
        }
        bind_resp = await client.post(
            f"{base_url}/placement.bind", json=bind_payload, headers=headers
        )
        bind_result = bind_resp.json()
        logger.info(f"placement.bind result: {bind_result}")

    # Return page with BX24.installFinish() + upload form
    return HTMLResponse(_install_page(success=True))


# ---------------------------------------------------------------------------
# Widget page (iframe content)
# ---------------------------------------------------------------------------

@router.get("/widget", response_class=HTMLResponse)
@router.post("/widget", response_class=HTMLResponse)
async def widget(
    request: Request,
    DOMAIN: str = Form(default=""),
    AUTH_ID: str = Form(default=""),
) -> HTMLResponse:
    """
    Served inside Bitrix24 as an iframe when user clicks the 'BuildControl' menu item.
    Shows a file upload form; on submit sends the file to /upload API.
    """
    return HTMLResponse(_widget_page())


@router.get("/rebind", response_class=HTMLResponse)
async def rebind_placement(domain: str = "", auth: str = "") -> HTMLResponse:
    """
    Re-register the LEFT_MENU placement with the current VPS_URL.

    Call this after a Cloudflare tunnel restart (when the VPS_URL changes)
    to update the handler URL in Bitrix24 so the sidebar icon keeps working.

    Usage: open {vps_url}/bitrix/rebind?domain=YOUR_DOMAIN&auth=YOUR_AUTH_TOKEN
    The auth token can be obtained from any recent Bitrix24 API call or from
    the app install page.
    """
    if not domain or not auth:
        return HTMLResponse(
            "<h2>Ошибка</h2><p>Укажите параметры: <code>?domain=YOUR_DOMAIN&amp;auth=AUTH_TOKEN</code></p>"
            "<p>Пример: <code>/bitrix/rebind?domain=mycompany.bitrix24.ru&amp;auth=abc123</code></p>",
            status_code=400,
        )

    vps_url = settings.vps_url
    base_url = f"https://{domain}/rest"
    headers = {"Content-Type": "application/json"}

    bind_payload = {
        "auth": auth,
        "PLACEMENT": "LEFT_MENU",
        "HANDLER": f"{vps_url}/bitrix/widget",
        "TITLE": WIDGET_TITLE,
        "LANG_ALL": {
            "ru": {"TITLE": "BuildControl"},
            "en": {"TITLE": "BuildControl"},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base_url}/placement.bind", json=bind_payload, headers=headers)
            result = resp.json()
        logger.info(f"rebind_placement: domain={domain} result={result}")
        ok = result.get("result") is True or result.get("result") == 1
        if ok:
            return HTMLResponse(
                f"<h2 style='color:green'>✓ Готово</h2>"
                f"<p>Виджет <strong>BuildControl</strong> успешно привязан к левой панели.<br>"
                f"Handler: <code>{vps_url}/bitrix/widget</code></p>"
            )
        else:
            detail = result.get("error_description") or result.get("error") or str(result)
            return HTMLResponse(
                f"<h2 style='color:orange'>⚠ Ответ Bitrix24</h2><p>{detail}</p>"
                f"<p>Если ошибка «already binded» — виджет уже зарегистрирован с этим handler-ом.</p>"
            )
    except Exception as e:
        logger.error(f"rebind_placement failed: {e}", exc_info=True)
        return HTMLResponse(
            f"<h2 style='color:red'>Ошибка</h2><p>{e}</p>",
            status_code=500,
        )


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

def _install_page(success: bool, error: str = "") -> str:
    """Install page: on success shows installFinish JS + upload form."""
    if success:
        finish_js = f"""
<script src="{BX24_JS_URL}"></script>
<script>
// BX24.install() is the correct callback for the install wizard.
// BX24.init() handlers do NOT fire until installFinish() is called,
// so putting installFinish() inside init() creates a deadlock.
if (typeof BX24 !== 'undefined') {{
  BX24.install(function() {{
    BX24.installFinish();
  }});
}}
</script>"""
        # Show the full tabbed app immediately so it's usable during install
        return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BuildControl</title>
{finish_js}
{_common_styles()}
</head>
<body>
{_tab_bar_html()}
<div id="tab-upload" class="tab-content" style="display:block;">
{_upload_form_html()}
</div>
<div id="tab-report" class="tab-content" style="display:none;">
{_report_form_html()}
</div>
<div id="tab-buyer" class="tab-content" style="display:none;">
{_buyer_report_form_html()}
</div>
<div id="tab-approval" class="tab-content" style="display:none;">
{_approval_tab_html()}
</div>
<script>
function switchTab(tabId) {{
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + tabId).style.display = 'block';
  event.currentTarget.classList.add('active');
  if (tabId === 'report') loadProjects();
  if (tabId === 'buyer') loadBuyerProjects();
  if (tabId === 'approval') loadPendingRequests();
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}
</script>
</body>
</html>"""
    else:
        return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Импорт Excel — Ошибка установки</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f7fa; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; }}
  .card {{ background: #fff; border-radius: 12px; padding: 40px; text-align: center;
           box-shadow: 0 2px 16px rgba(0,0,0,0.08); max-width: 400px; width: 90%; }}
  .card .icon {{ color: #e74c3c; font-size: 48px; margin-bottom: 16px; }}
  h2 {{ color: #2c3e50; margin-bottom: 12px; }}
  p {{ color: #555; line-height: 1.5; }}
</style>
</head>
<body>
<div class="card">
  <div class="icon">✗</div>
  <h2>Ошибка установки</h2>
  <p>{error}</p>
</div>
</body>
</html>"""


def _widget_page() -> str:
    """Widget page: tabbed interface with upload form, foreman report, and buyer report."""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BuildControl</title>
<script src="{BX24_JS_URL}"></script>
{_common_styles()}
</head>
<body>
{_tab_bar_html()}
<div id="tab-upload" class="tab-content" style="display:block;">
{_upload_form_html()}
</div>
<div id="tab-report" class="tab-content" style="display:none;">
{_report_form_html()}
</div>
<div id="tab-buyer" class="tab-content" style="display:none;">
{_buyer_report_form_html()}
</div>
<div id="tab-approval" class="tab-content" style="display:none;">
{_approval_tab_html()}
</div>
<script>
if (typeof BX24 !== 'undefined') {{
  BX24.init(function() {{
    BX24.fitWindow();
  }});
}}

function switchTab(tabId) {{
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + tabId).style.display = 'block';
  event.currentTarget.classList.add('active');
  if (tabId === 'report') loadProjects();
  if (tabId === 'buyer') loadBuyerProjects();
  if (tabId === 'approval') loadPendingRequests();
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}
</script>
</body>
</html>"""


def _common_styles() -> str:
    """Shared CSS for install and widget pages."""
    return """<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f5f7fa;
    padding: 24px;
    color: #2c3e50;
  }
  h1 { font-size: 20px; font-weight: 600; margin-bottom: 6px; }
  .subtitle { color: #7f8c8d; font-size: 13px; margin-bottom: 24px; }

  /* Tab navigation */
  .tab-bar {
    display: flex;
    gap: 0;
    margin-bottom: 20px;
    border-bottom: 2px solid #e0e4e8;
  }
  .tab-btn {
    padding: 10px 20px;
    border: none;
    background: none;
    font-size: 14px;
    font-weight: 500;
    color: #7f8c8d;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    transition: all .2s;
  }
  .tab-btn:hover { color: #2c3e50; }
  .tab-btn.active {
    color: #2980b9;
    border-bottom-color: #2980b9;
  }
  .tab-content { display: none; }

  /* Report form styles */
  .form-group { margin-bottom: 18px; }
  .form-group label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: #555;
    margin-bottom: 6px;
  }
  .form-group select,
  .form-group input[type="date"],
  .form-group input[type="number"],
  .form-group input[type="text"],
  .form-group textarea {
    width: 100%;
    padding: 9px 12px;
    border: 1px solid #d5d8dc;
    border-radius: 6px;
    font-size: 14px;
    font-family: inherit;
    background: #fff;
  }
  .form-group textarea { resize: vertical; min-height: 60px; }

  .section-title {
    font-size: 15px;
    font-weight: 600;
    color: #2c3e50;
    margin: 20px 0 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid #e0e4e8;
  }

  .dynamic-row {
    display: flex;
    gap: 8px;
    align-items: flex-end;
    margin-bottom: 8px;
    background: #fff;
    padding: 10px;
    border-radius: 8px;
    border: 1px solid #e8eaed;
  }
  .dynamic-row .field { flex: 1; }
  .dynamic-row .field-sm { flex: 0 0 80px; }
  .dynamic-row .field-unit { flex: 0 0 60px; font-size: 13px; color: #7f8c8d; padding-bottom: 10px; }
  .dynamic-row .field label { font-size: 12px; color: #888; margin-bottom: 4px; }
  .dynamic-row .field select,
  .dynamic-row .field input {
    width: 100%;
    padding: 7px 8px;
    border: 1px solid #d5d8dc;
    border-radius: 5px;
    font-size: 13px;
  }
  .dynamic-row .remove-btn {
    flex: 0 0 32px;
    height: 32px;
    border: none;
    background: #fdedec;
    color: #c0392b;
    border-radius: 6px;
    cursor: pointer;
    font-size: 16px;
    margin-bottom: 0;
  }
  .dynamic-row .remove-btn:hover { background: #f5b7b1; }

  .add-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    border: 1px dashed #bdc3c7;
    border-radius: 6px;
    background: none;
    color: #2980b9;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    margin-top: 4px;
  }
  .add-btn:hover { border-color: #2980b9; background: #eaf4fb; }

  button#submitReport,
  button#submitBuyerReport {
    width: 100%;
    padding: 12px;
    background: #27ae60;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: background .2s;
    margin-top: 16px;
  }
  button#submitReport:hover:not(:disabled),
  button#submitBuyerReport:hover:not(:disabled) { background: #219a52; }
  button#submitReport:disabled,
  button#submitBuyerReport:disabled { background: #a9dfbf; cursor: not-allowed; }

  #reportResult,
  #buyerResult {
    display: none;
    margin-top: 16px;
    background: #eafaf1;
    border: 1px solid #a9dfbf;
    border-radius: 8px;
    padding: 14px;
  }
  #reportResult h3, #buyerResult h3 { font-size: 15px; color: #27ae60; margin-bottom: 6px; }
  #reportResult p, #buyerResult p { font-size: 13px; color: #555; }

  #reportError,
  #buyerError {
    display: none;
    margin-top: 16px;
    background: #fdedec;
    border: 1px solid #f5b7b1;
    border-radius: 8px;
    padding: 14px;
    color: #c0392b;
    font-size: 13px;
  }

  .upload-zone {
    border: 2px dashed #bdc3c7;
    border-radius: 10px;
    padding: 32px 24px;
    text-align: center;
    cursor: pointer;
    transition: border-color .2s, background .2s;
    background: #fff;
    margin-bottom: 16px;
  }
  .upload-zone:hover, .upload-zone.drag { border-color: #3498db; background: #eaf4fb; }
  .upload-zone .icon { font-size: 36px; margin-bottom: 10px; }
  .upload-zone p { color: #7f8c8d; font-size: 14px; }
  .upload-zone .filename { color: #2980b9; font-weight: 500; font-size: 14px; margin-top: 8px; }

  input[type=file] { display: none; }

  /* Multi-task report blocks */
  .task-block {
    border: 1px solid #d5d8dc;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 16px;
    background: #f8f9fa;
    position: relative;
  }
  .task-block-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
  }
  .task-block-header label { font-size: 13px; font-weight: 600; color: #2c3e50; white-space: nowrap; }
  .task-block-header select { flex: 1; padding: 8px 10px; border: 1px solid #d5d8dc; border-radius: 6px; font-size: 13px; }
  .task-block-remove {
    flex: 0 0 32px; height: 32px; border: none; background: #fdedec;
    color: #c0392b; border-radius: 6px; cursor: pointer; font-size: 16px;
  }
  .task-block-remove:hover { background: #f5b7b1; }
  .task-block .section-title { font-size: 13px; margin: 14px 0 8px; }
  .add-task-btn {
    display: block; width: 100%; padding: 10px;
    border: 2px dashed #bdc3c7; border-radius: 8px;
    background: none; color: #2980b9; font-size: 13px;
    font-weight: 600; cursor: pointer; margin-bottom: 16px;
  }
  .add-task-btn:hover { border-color: #2980b9; background: #eaf4fb; }

  button#importBtn {
    width: 100%;
    padding: 12px;
    background: #2980b9;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: background .2s;
  }
  button#importBtn:hover:not(:disabled) { background: #1a6fa0; }
  button#importBtn:disabled { background: #a0c4dd; cursor: not-allowed; }

  #progress {
    display: none;
    margin-top: 16px;
  }
  #progress .progress-title {
    font-size: 13px;
    color: #7f8c8d;
    margin-bottom: 10px;
    text-align: center;
  }
  .step {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 10px;
    margin: 3px 0;
    border-radius: 6px;
    font-size: 14px;
    color: #bdc3c7;
    transition: all .3s;
  }
  .step.active {
    color: #2980b9;
    background: #eaf4fb;
    font-weight: 500;
  }
  .step.done { color: #27ae60; }
  .step-dot {
    width: 18px; height: 18px;
    border-radius: 50%;
    background: #ecf0f1;
    display: flex; align-items: center; justify-content: center;
    font-size: 11px;
    flex-shrink: 0;
    transition: all .3s;
  }
  .step.active .step-dot {
    border: 2px solid #2980b9;
    border-top-color: transparent;
    background: transparent;
    animation: spin .8s linear infinite;
  }
  .step.done .step-dot {
    background: #27ae60;
    color: #fff;
    font-size: 12px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  #result {
    display: none;
    margin-top: 20px;
    background: #eafaf1;
    border: 1px solid #a9dfbf;
    border-radius: 8px;
    padding: 16px;
  }
  #result h3 { font-size: 15px; color: #27ae60; margin-bottom: 10px; }
  #result .stat { font-size: 13px; color: #555; margin: 4px 0; }
  #result .links { margin-top: 12px; }
  #result .links a {
    display: inline-block;
    margin: 4px 6px 4px 0;
    padding: 6px 14px;
    background: #2980b9;
    color: #fff;
    border-radius: 6px;
    text-decoration: none;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
  }
  #result .links a:hover { background: #1a6fa0; }

  #error {
    display: none;
    margin-top: 20px;
    background: #fdedec;
    border: 1px solid #f5b7b1;
    border-radius: 8px;
    padding: 14px;
    color: #c0392b;
    font-size: 13px;
  }
  #error strong { display: block; margin-bottom: 4px; font-size: 14px; }
</style>"""


def _tab_bar_html() -> str:
    """Tab bar for switching between Upload, Foreman Report, Buyer Report, and Approval sections."""
    return """
<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('upload')">Импорт Excel</button>
  <button class="tab-btn" onclick="switchTab('report')">Отчет прораба</button>
  <button class="tab-btn" onclick="switchTab('buyer')">Заявка на закупку</button>
  <button class="tab-btn" onclick="switchTab('approval')">Согласование</button>
</div>"""


def _report_form_html() -> str:
    """Report form HTML for the foreman daily report."""
    vps_url = settings.vps_url
    return f"""
<h1>Отчет прораба</h1>
<p class="subtitle">Ежедневный отчет по материалам, трудозатратам и технике</p>

<div class="form-group">
  <label>Проект</label>
  <select id="reportProject" onchange="onProjectChange()">
    <option value="">Загрузка проектов...</option>
  </select>
</div>

<div class="form-group">
  <label>Дата отчета</label>
  <input type="date" id="reportDate">
</div>

<div id="tasksContainer"></div>
<button type="button" class="add-task-btn" id="addTaskBtn" onclick="addTaskBlock()" disabled>
  + Добавить задачу
</button>

<div class="form-group" style="margin-top: 16px;">
  <label>Общий комментарий</label>
  <textarea id="reportComments" placeholder="Заметки по работе за день..."></textarea>
</div>

<button id="submitReport" onclick="submitReport()" disabled>Отправить отчет</button>

<div id="reportResult">
  <h3>Отчет отправлен!</h3>
  <p id="reportResultMsg"></p>
</div>
<div id="reportError"></div>

<script>
const API_URL = "{vps_url}/api";
let projectTasks = [];       // all tasks for current project (shared, used to fill task selects)
let projectStages = [];      // kanban stages for current project (used for v3 tasks)
let taskBlockData = {{}};     // blockIdx -> {{ etap, zadacha, materials, workers, equipment, subtasks, stage_id, has_subtasks, loading_resources }}
let taskBlockCounter = 0;
let currentProjectId = null;
let projectLoadSeq = 0;
let taskLoadSeqByBlock = {{}};

// Set default date to today
document.getElementById('reportDate').valueAsDate = new Date();

async function loadProjects() {{
  const sel = document.getElementById('reportProject');
  try {{
    const resp = await fetch(API_URL + '/projects');
    if (!resp.ok) throw new Error('Ошибка сервера ' + resp.status);
    const data = await resp.json();
    sel.innerHTML = '<option value="">-- Выберите проект --</option>';
    data.forEach(p => {{
      sel.innerHTML += `<option value="${{p.id}}">${{p.name}}</option>`;
    }});
  }} catch(e) {{
    sel.innerHTML = `<option value="">Ошибка загрузки: ${{e.message}}</option>`;
  }}
}}

async function onProjectChange() {{
  const loadSeq = ++projectLoadSeq;
  const pid = document.getElementById('reportProject').value;
  document.getElementById('submitReport').disabled = true;
  document.getElementById('addTaskBtn').disabled = true;
  document.getElementById('tasksContainer').innerHTML = '';
  projectTasks = [];
  projectStages = [];
  taskBlockData = {{}};
  taskBlockCounter = 0;
  taskLoadSeqByBlock = {{}};
  currentProjectId = pid || null;

  if (!pid) return;

  try {{
    const [tasksResp, stagesResp] = await Promise.all([
      fetch(API_URL + '/projects/' + pid + '/tasks'),
      fetch(API_URL + '/projects/' + pid + '/stages'),
    ]);
    if (!tasksResp.ok) throw new Error('Ошибка загрузки задач');
    if (loadSeq !== projectLoadSeq) return;  // stale response after project switch
    projectTasks = await tasksResp.json();
    projectStages = stagesResp.ok ? await stagesResp.json() : [];
    document.getElementById('addTaskBtn').disabled = false;
    addTaskBlock();  // add first task block automatically
  }} catch(e) {{
    if (loadSeq !== projectLoadSeq) return;
    document.getElementById('tasksContainer').innerHTML =
      `<p style="color:#c0392b">Ошибка загрузки задач: ${{e.message}}</p>`;
  }}
}}

function _buildTaskSelectHtml() {{
  let html = '<option value="">-- Выберите задачу --</option>';
  const byEtap = {{}};
  projectTasks.forEach((t, i) => {{
    if (!byEtap[t.etap]) byEtap[t.etap] = [];
    byEtap[t.etap].push({{ ...t, idx: i }});
  }});
  for (const [etap, tasks] of Object.entries(byEtap)) {{
    html += `<optgroup label="${{etap}}">`;
    tasks.forEach(t => {{
      html += `<option value="${{t.idx}}" data-etap="${{t.etap}}" data-zadacha="${{t.zadacha}}">${{t.zadacha}}</option>`;
    }});
    html += '</optgroup>';
  }}
  return html;
}}

function _statusBadge(status) {{
  const s = (status || 'Новая').trim();
  const color = s.includes('Завершен') ? '#27ae60' : s.includes('работ') ? '#e67e22' : '#7f8c8d';
  return `<span style="font-size:11px;padding:2px 7px;border-radius:10px;background:${{color}};color:#fff">${{s}}</span>`;
}}

function _buildStageSelectHtml() {{
  let html = '<option value="">-- Выберите стадию --</option>';
  projectStages.forEach(stage => {{
    html += `<option value="${{stage.id}}">${{stage.title}}</option>`;
  }});
  return html;
}}

function _syncResourceButtons(idx) {{
  const data = taskBlockData[idx];
  const block = document.querySelector(`.task-block[data-block-idx="${{idx}}"]`);
  if (!data || !block) return;
  const disabled = !data.etap || !data.zadacha || !!data.loading_resources;
  block.querySelectorAll('.add-resource-btn').forEach(btn => {{
    btn.disabled = disabled;
  }});
}}

function _buildMaterialOptions(materials) {{
  let opts = '<option value="">-- Материал --</option>';
  (materials || []).forEach((m, i) => {{
    opts += `<option value="${{i}}" data-unit="${{m.unit || ''}}" data-stock="${{m.stock ?? ''}}">${{m.name}}</option>`;
  }});
  return opts;
}}

function _buildLaborOptions(workers) {{
  let opts = '<option value="">-- Работник --</option>';
  (workers || []).forEach((w, i) => {{
    opts += `<option value="${{i}}" data-role="${{w.role || ''}}">${{w.name}}</option>`;
  }});
  return opts;
}}

function _buildEquipmentOptions(equipment) {{
  let opts = '<option value="">-- Техника --</option>';
  (equipment || []).forEach((e, i) => {{
    opts += `<option value="${{i}}">${{e.name}}</option>`;
  }});
  return opts;
}}

function _backfillResourceRows(idx) {{
  const data = taskBlockData[idx];
  const block = document.querySelector(`.task-block[data-block-idx="${{idx}}"]`);
  if (!data || !block) return;

  const matOptions = _buildMaterialOptions(data.materials);
  block.querySelectorAll('.mat-select').forEach(sel => {{
    const prevValue = sel.value;
    sel.innerHTML = matOptions;
    if ([...sel.options].some(o => o.value === prevValue)) sel.value = prevValue;
    onMaterialSelect(sel);
  }});

  const laborOptions = _buildLaborOptions(data.workers);
  block.querySelectorAll('.lab-select').forEach(sel => {{
    const prevValue = sel.value;
    sel.innerHTML = laborOptions;
    if ([...sel.options].some(o => o.value === prevValue)) sel.value = prevValue;
  }});

  const equipmentOptions = _buildEquipmentOptions(data.equipment);
  block.querySelectorAll('.eq-select').forEach(sel => {{
    const prevValue = sel.value;
    sel.innerHTML = equipmentOptions;
    if ([...sel.options].some(o => o.value === prevValue)) sel.value = prevValue;
  }});
}}

function renderSubtaskList(idx, subtasks) {{
  const container = document.querySelector(`.subtask-container-${{idx}}`);
  if (!container) return;
  if (!subtasks || !subtasks.length) {{
    container.innerHTML = '<p style="color:#888;font-size:12px;margin:4px 0">Подзадачи не заданы</p>';
    return;
  }}
  let html = '<div style="display:flex;flex-direction:column;gap:6px;">';
  subtasks.forEach(sub => {{
    const dl = sub.deadline_plan ? ` · срок: ${{sub.deadline_plan.slice(0,10)}}` : '';
    html += `
    <div class="subtask-row" data-elem-id="${{sub.element_id}}" data-status="${{sub.status || 'Новая'}}"
         style="display:flex;align-items:center;gap:8px;padding:6px 8px;background:#f8f9fa;border-radius:6px;flex-wrap:wrap;">
      <span style="flex:1;font-size:13px">${{sub.title}}<span style="color:#aaa;font-size:11px">${{dl}}</span></span>
      <span class="sub-badge">${{_statusBadge(sub.status)}}</span>
      <button type="button" onclick="setSubtaskStatus(${{idx}}, this, 'started')"
        style="padding:3px 10px;font-size:12px;border:1px solid #e67e22;color:#e67e22;background:#fff;border-radius:4px;cursor:pointer">
        ▶ В работе
      </button>
      <button type="button" onclick="setSubtaskStatus(${{idx}}, this, 'done')"
        style="padding:3px 10px;font-size:12px;border:1px solid #27ae60;color:#27ae60;background:#fff;border-radius:4px;cursor:pointer">
        ✓ Готово
      </button>
    </div>`;
  }});
  html += '</div>';
  container.innerHTML = html;
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

function setSubtaskStatus(blockIdx, btn, status) {{
  const row = btn.closest('.subtask-row');
  row.dataset.pendingStatus = status;
  row.querySelector('.sub-badge').innerHTML = _statusBadge(status === 'done' ? 'Завершена' : 'В работе');
  // Highlight the active button
  row.querySelectorAll('button').forEach(b => b.style.fontWeight = '');
  btn.style.fontWeight = 'bold';
}}

function addTaskBlock() {{
  const idx = taskBlockCounter++;
  taskBlockData[idx] = {{
    etap: '',
    zadacha: '',
    materials: [],
    workers: [],
    equipment: [],
    subtasks: [],
    has_subtasks: false,
    stage_id: null,
    loading_resources: false
  }};

  const block = document.createElement('div');
  block.className = 'task-block';
  block.dataset.blockIdx = idx;
  block.innerHTML = `
    <div class="task-block-header">
      <label>Задача</label>
      <select onchange="onTaskBlockChange(this, ${{idx}})">
        ${{_buildTaskSelectHtml()}}
      </select>
      <button type="button" class="task-block-remove" onclick="removeTaskBlock(${{idx}})">×</button>
    </div>

    <div class="section-title">Материалы</div>
    <div class="mat-container-${{idx}}"></div>
    <button type="button" class="add-btn add-resource-btn" onclick="addMaterialRow(${{idx}})" disabled>+ Добавить материал</button>

    <div class="section-title">Трудозатраты</div>
    <div class="lab-container-${{idx}}"></div>
    <button type="button" class="add-btn add-resource-btn" onclick="addLaborRow(${{idx}})" disabled>+ Добавить работника</button>

    <div class="section-title">Техника</div>
    <div class="eq-container-${{idx}}"></div>
    <button type="button" class="add-btn add-resource-btn" onclick="addEquipmentRow(${{idx}})" disabled>+ Добавить технику</button>

    <div class="section-title">Прогресс задачи</div>
    <div class="subtask-container-${{idx}}" style="margin-bottom:8px;">
      <p style="color:#aaa;font-size:12px;margin:4px 0">Выберите задачу для загрузки подзадач</p>
    </div>
    <div class="stage-container-${{idx}}" style="display:none;margin-bottom:8px;">
      <label style="font-size:12px;color:#555;display:block;margin-bottom:4px;">Стадия задачи (v3)</label>
      <select class="stage-select" onchange="onStageChange(this, ${{idx}})" style="width:100%;padding:7px 8px;border:1px solid #d5d8dc;border-radius:5px;font-size:13px;">
        <option value="">-- Выберите стадию --</option>
      </select>
    </div>
    <div style="margin-top:6px;">
      <label style="font-size:12px;color:#888;display:block;margin-bottom:4px;">Комментарий к задаче</label>
      <textarea class="task-comment-input" placeholder="Что сделано, замечания..." style="width:100%;padding:7px 8px;border:1px solid #d5d8dc;border-radius:5px;font-size:13px;resize:vertical;min-height:56px;font-family:inherit;box-sizing:border-box;"></textarea>
    </div>
  `;
  document.getElementById('tasksContainer').appendChild(block);
  _syncResourceButtons(idx);
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

function removeTaskBlock(idx) {{
  const block = document.querySelector(`.task-block[data-block-idx="${{idx}}"]`);
  if (block) block.remove();
  delete taskBlockData[idx];
  delete taskLoadSeqByBlock[idx];
  _updateSubmitBtn();
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

function onStageChange(sel, idx) {{
  const data = taskBlockData[idx];
  if (!data) return;
  data.stage_id = sel.value ? parseInt(sel.value) : null;
}}

function renderProgressControls(idx) {{
  const data = taskBlockData[idx];
  if (!data) return;
  const stageContainer = document.querySelector(`.stage-container-${{idx}}`);
  const stageSelect = stageContainer ? stageContainer.querySelector('.stage-select') : null;
  const subContainer = document.querySelector(`.subtask-container-${{idx}}`);
  if (!stageContainer || !stageSelect || !subContainer) return;

  if (data.subtasks.length > 0) {{
    data.has_subtasks = true;
    data.stage_id = null;
    stageContainer.style.display = 'none';
  }} else {{
    data.has_subtasks = false;
    stageContainer.style.display = 'block';
    stageSelect.innerHTML = _buildStageSelectHtml();
    if (data.stage_id) stageSelect.value = String(data.stage_id);
    if (!projectStages.length) {{
      stageContainer.style.display = 'none';
    }}
    subContainer.innerHTML = '<p style="color:#888;font-size:12px;margin:4px 0">Подзадач нет — используйте выбор стадии.</p>';
  }}
}}

async function onTaskBlockChange(sel, idx) {{
  const data = taskBlockData[idx];
  if (!data) return;
  const opt = sel.options[sel.selectedIndex];
  data.etap = '';
  data.zadacha = '';
  data.materials = [];
  data.workers = [];
  data.equipment = [];
  data.subtasks = [];
  data.has_subtasks = false;
  data.stage_id = null;
  data.loading_resources = false;
  _syncResourceButtons(idx);

  // Clear existing resource rows and subtask list for this block
  document.querySelector(`.mat-container-${{idx}}`).innerHTML = '';
  document.querySelector(`.lab-container-${{idx}}`).innerHTML = '';
  document.querySelector(`.eq-container-${{idx}}`).innerHTML = '';
  const subContainer = document.querySelector(`.subtask-container-${{idx}}`);
  if (subContainer) subContainer.innerHTML = '<p style="color:#aaa;font-size:12px;margin:4px 0">Загрузка подзадач...</p>';
  const stageContainer = document.querySelector(`.stage-container-${{idx}}`);
  if (stageContainer) {{
    stageContainer.style.display = 'none';
    const stageSelect = stageContainer.querySelector('.stage-select');
    if (stageSelect) stageSelect.innerHTML = '<option value="">-- Выберите стадию --</option>';
  }}

  if (!opt || !opt.dataset.etap) {{
    _syncResourceButtons(idx);
    _updateSubmitBtn();
    return;
  }}

  const etap = opt.dataset.etap;
  const zadacha = opt.dataset.zadacha;
  data.etap = etap;
  data.zadacha = zadacha;
  data.loading_resources = true;
  _syncResourceButtons(idx);
  _updateSubmitBtn();
  const requestSeq = (taskLoadSeqByBlock[idx] || 0) + 1;
  taskLoadSeqByBlock[idx] = requestSeq;

  const pid = currentProjectId;
  const params = `?etap=${{encodeURIComponent(etap)}}&zadacha=${{encodeURIComponent(zadacha)}}`;
  let ctx = null;

  try {{
    const resp = await fetch(API_URL + '/projects/' + pid + '/task-context' + params);
    if (!resp.ok) throw new Error('Ошибка загрузки ресурсов задачи');
    ctx = await resp.json();
  }} catch(e) {{
    console.error('Failed to load task resources for block', idx, e);
    const activeSubContainer = document.querySelector(`.subtask-container-${{idx}}`);
    if (activeSubContainer) {{
      activeSubContainer.innerHTML = '<p style="color:#c0392b;font-size:12px;margin:4px 0">Ошибка загрузки ресурсов задачи</p>';
    }}
  }}

  // Ignore stale response if user switched task/project meanwhile
  if (taskLoadSeqByBlock[idx] !== requestSeq) return;
  if (!taskBlockData[idx]) return;
  if (String(currentProjectId) !== String(pid)) return;
  if (taskBlockData[idx].etap !== etap || taskBlockData[idx].zadacha !== zadacha) return;

  const ctxMaterials = ctx && Array.isArray(ctx.materials) ? ctx.materials : [];
  const ctxLabor = ctx && Array.isArray(ctx.labor) ? ctx.labor : [];
  const ctxEquipment = ctx && Array.isArray(ctx.equipment) ? ctx.equipment : [];
  const ctxSubtasks = ctx && Array.isArray(ctx.subtasks) ? ctx.subtasks : [];
  taskBlockData[idx].materials = ctxMaterials;
  taskBlockData[idx].workers = ctxLabor;
  taskBlockData[idx].equipment = ctxEquipment;
  taskBlockData[idx].subtasks = ctxSubtasks;
  taskBlockData[idx].loading_resources = false;

  _backfillResourceRows(idx);
  _syncResourceButtons(idx);

  // Render subtask list + stage selector mode
  if (ctx) {{
    renderSubtaskList(idx, taskBlockData[idx].subtasks);
  }} else {{
    const activeSubContainer = document.querySelector(`.subtask-container-${{idx}}`);
    if (activeSubContainer) {{
      activeSubContainer.innerHTML = '<p style="color:#888;font-size:12px;margin:4px 0">Подзадачи не загружены</p>';
    }}
  }}
  renderProgressControls(idx);

  _updateSubmitBtn();
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

function _updateSubmitBtn() {{
  const hasTask = Object.values(taskBlockData).some(d => d.etap && d.zadacha);
  const hasLoading = Object.values(taskBlockData).some(d => d.loading_resources);
  document.getElementById('submitReport').disabled = !hasTask || hasLoading;
}}

function addMaterialRow(idx) {{
  const data = taskBlockData[idx];
  if (!data || data.loading_resources || !data.etap || !data.zadacha) return;
  const opts = _buildMaterialOptions(data.materials);
  const row = document.createElement('div');
  row.className = 'dynamic-row';
  row.style.flexWrap = 'wrap';
  row.innerHTML = `
    <div class="field"><label>Материал</label>
      <select class="mat-select" onchange="onMaterialSelect(this)">${{opts}}</select></div>
    <div class="field field-sm">
      <label>Кол-во</label>
      <input type="number" class="mat-qty" min="0" step="0.01" placeholder="0" oninput="onMatQtyInput(this)">
      <div class="stock-hint" style="font-size:11px;color:#7f8c8d;margin-top:2px;"></div>
    </div>
    <div class="field-unit mat-unit"></div>
    <div class="field"><label>Комментарий</label>
      <input type="text" class="mat-comment" placeholder=""></div>
    <button type="button" class="remove-btn" onclick="this.parentElement.remove()">×</button>
  `;
  document.querySelector(`.mat-container-${{idx}}`).appendChild(row);
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

function onMaterialSelect(sel) {{
  const row = sel.closest('.dynamic-row');
  const opt = sel.options[sel.selectedIndex];
  row.querySelector('.mat-unit').textContent = opt.dataset.unit || '';
  const stock = parseFloat(opt.dataset.stock);
  const qtyInput = row.querySelector('.mat-qty');
  const stockHint = row.querySelector('.stock-hint');
  if (isNaN(stock)) {{
    qtyInput.removeAttribute('max');
    stockHint.textContent = '';
  }} else {{
    qtyInput.max = stock;
    stockHint.textContent = `На складе: ${{stock}}`;
    stockHint.style.color = '#7f8c8d';
  }}
  qtyInput.style.borderColor = '';
  onMatQtyInput(qtyInput);
}}

function onMatQtyInput(input) {{
  const max = parseFloat(input.max);
  const val = parseFloat(input.value);
  const hint = input.parentElement.querySelector('.stock-hint');
  if (!isNaN(max) && !isNaN(val) && val > max) {{
    input.style.borderColor = '#e74c3c';
    if (hint) {{ hint.textContent = `⚠ Превышает остаток на складе (${{max}})`; hint.style.color = '#e74c3c'; }}
  }} else {{
    input.style.borderColor = '';
    if (hint && !isNaN(max)) {{ hint.textContent = `На складе: ${{max}}`; hint.style.color = '#7f8c8d'; }}
  }}
}}

function addLaborRow(idx) {{
  const data = taskBlockData[idx];
  if (!data || data.loading_resources || !data.etap || !data.zadacha) return;
  const opts = _buildLaborOptions(data.workers);
  const row = document.createElement('div');
  row.className = 'dynamic-row';
  row.innerHTML = `
    <div class="field"><label>Работник</label>
      <select class="lab-select">${{opts}}</select></div>
    <div class="field field-sm"><label>Часы</label>
      <input type="number" class="lab-hours" min="0" step="0.5" placeholder="0"></div>
    <button type="button" class="remove-btn" onclick="this.parentElement.remove()">×</button>
  `;
  document.querySelector(`.lab-container-${{idx}}`).appendChild(row);
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

function addEquipmentRow(idx) {{
  const data = taskBlockData[idx];
  if (!data || data.loading_resources || !data.etap || !data.zadacha) return;
  const opts = _buildEquipmentOptions(data.equipment);
  const row = document.createElement('div');
  row.className = 'dynamic-row';
  row.innerHTML = `
    <div class="field"><label>Техника</label>
      <select class="eq-select">${{opts}}</select></div>
    <div class="field field-sm"><label>Часы</label>
      <input type="number" class="eq-hours" min="0" step="0.5" placeholder="0"></div>
    <button type="button" class="remove-btn" onclick="this.parentElement.remove()">×</button>
  `;
  document.querySelector(`.eq-container-${{idx}}`).appendChild(row);
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

async function submitReport() {{
  const pid = currentProjectId;
  if (!pid) return;
  const hasLoading = Object.values(taskBlockData).some(d => d.loading_resources);
  if (hasLoading) {{
    showEl('reportError');
    document.getElementById('reportError').textContent =
      'Подождите завершения загрузки данных задачи и попробуйте снова.';
    return;
  }}

  const reportDate = document.getElementById('reportDate').value;
  const comments = document.getElementById('reportComments').value;

  // Collect per-task data from all task blocks
  const tasksPayload = [];
  document.querySelectorAll('.task-block').forEach(block => {{
    const idx = parseInt(block.dataset.blockIdx);
    const d = taskBlockData[idx];
    if (!d || !d.etap || !d.zadacha) return;

    const materials = [];
    block.querySelectorAll('.dynamic-row').forEach(row => {{
      const matSel = row.querySelector('.mat-select');
      if (!matSel) return;
      const i = matSel.value;
      if (i === '') return;
      const m = d.materials[parseInt(i)];
      materials.push({{
        name: m.name,
        quantity: parseFloat(row.querySelector('.mat-qty').value) || 0,
        unit: m.unit || '',
        comment: row.querySelector('.mat-comment').value || ''
      }});
    }});

    const labor = [];
    block.querySelectorAll('.dynamic-row').forEach(row => {{
      const labSel = row.querySelector('.lab-select');
      if (!labSel) return;
      const i = labSel.value;
      if (i === '') return;
      const w = d.workers[parseInt(i)];
      labor.push({{
        worker_name: w.name,
        hours: parseFloat(row.querySelector('.lab-hours').value) || 0,
        role: w.role || ''
      }});
    }});

    const equipment = [];
    block.querySelectorAll('.dynamic-row').forEach(row => {{
      const eqSel = row.querySelector('.eq-select');
      if (!eqSel) return;
      const i = eqSel.value;
      if (i === '') return;
      const e = d.equipment[parseInt(i)];
      equipment.push({{
        name: e.name,
        hours: parseFloat(row.querySelector('.eq-hours').value) || 0
      }});
    }});

    // Collect subtask status updates (only rows where foreman clicked a button)
    const subtaskUpdates = [];
    block.querySelectorAll('.subtask-row').forEach(row => {{
      const pendingStatus = row.dataset.pendingStatus;
      const elemId = row.dataset.elemId;
      if (pendingStatus && elemId) {{
        subtaskUpdates.push({{ element_id: parseInt(elemId), status: pendingStatus }});
      }}
    }});

    const commentInput = block.querySelector('.task-comment-input');
    const commentVal = commentInput ? commentInput.value.trim() : '';

    tasksPayload.push({{
      task_etap: d.etap,
      task_zadacha: d.zadacha,
      subtask_updates: subtaskUpdates,
      stage_id: d.has_subtasks ? null : d.stage_id,
      comment: commentVal,
      materials,
      labor,
      equipment
    }});
  }});

  if (!tasksPayload.length) return;

  // Pre-submit: check if any material qty exceeds stock
  let stockViolation = false;
  document.querySelectorAll('.task-block .mat-qty').forEach(input => {{
    const max = parseFloat(input.max);
    const val = parseFloat(input.value);
    if (!isNaN(max) && !isNaN(val) && val > max) stockViolation = true;
  }});
  if (stockViolation) {{
    showEl('reportError');
    document.getElementById('reportError').textContent =
      'Ошибка: количество одного из материалов превышает остаток на складе. Исправьте значения перед отправкой.';
    return;
  }}

  const btn = document.getElementById('submitReport');
  btn.disabled = true;
  btn.textContent = 'Отправка...';
  hideEl('reportResult');
  hideEl('reportError');

  try {{
    const resp = await fetch(API_URL + '/report', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        project_id: parseInt(pid),
        date: reportDate,
        comments: comments,
        tasks: tasksPayload,
      }})
    }});
    let data = {{}};
    try {{ data = await resp.json(); }} catch (_) {{}}
    if (!resp.ok) throw new Error(data.detail || 'Ошибка сервера ' + resp.status);

    // Reset form after success
    document.getElementById('tasksContainer').innerHTML = '';
    document.getElementById('reportComments').value = '';
    document.getElementById('reportProject').value = '';
    document.getElementById('submitReport').disabled = true;
    document.getElementById('addTaskBtn').disabled = true;
    projectTasks = [];
    taskBlockData = {{}};
    taskBlockCounter = 0;
    currentProjectId = null;

    showEl('reportResult');
    document.getElementById('reportResultMsg').textContent =
      'Отчет за ' + reportDate + ' успешно сохранен.';
    if (typeof BX24 !== 'undefined') BX24.fitWindow();
  }} catch(e) {{
    showEl('reportError');
    document.getElementById('reportError').textContent = 'Ошибка: ' + e.message;
  }} finally {{
    btn.disabled = false;
    btn.textContent = 'Отправить отчет';
  }}
}}

function showEl(id) {{ document.getElementById(id).style.display = 'block'; }}
function hideEl(id) {{ document.getElementById(id).style.display = 'none'; }}
</script>
"""


def _buyer_report_form_html() -> str:
    """Buyer (закупщик) form: submits a procurement request for approval."""
    vps_url = settings.vps_url
    max_mb = settings.max_proposal_file_mb
    return f"""
<h1>Заявка на закупку</h1>
<p class="subtitle">Укажите материалы и приложите счёт или коммерческое предложение поставщика — заявка уйдёт на согласование</p>

<div class="form-group">
  <label>Проект</label>
  <select id="buyerProject" onchange="onBuyerProjectChange()">
    <option value="">Загрузка проектов...</option>
  </select>
</div>

<div class="form-group">
  <label>Дата</label>
  <input type="date" id="buyerDate">
</div>

<div class="section-title">Материалы для закупки</div>
<div id="buyerItemsContainer"></div>
<button type="button" class="add-btn" onclick="addBuyerRow()">+ Добавить материал</button>

<div class="form-group" style="margin-top:18px;">
  <label>Комментарий (обязателен, если цена выше плановой)</label>
  <textarea id="buyerComment" rows="3"
            placeholder="Если цена выше плановой — обязательно укажите причину повышения"
            oninput="updateBuyerCommentState()"></textarea>
  <div id="buyerCommentHint" style="font-size:12px;margin-top:4px;color:#7f8c8d;"></div>
</div>

<div class="form-group">
  <label>Счёт или коммерческое предложение (PDF, до {max_mb} МБ) <span style="color:#c0392b;">*</span></label>
  <input type="file" id="buyerProposal" accept=".pdf" required onchange="updateBuyerCommentState()">
</div>

<button id="submitBuyerReport" onclick="submitBuyerReport()" disabled>Отправить заявку на согласование</button>

<div id="buyerResult">
  <h3>Заявка отправлена!</h3>
  <p id="buyerResultMsg"></p>
</div>
<div id="buyerError"></div>

<script>
const BUYER_API_URL = "{vps_url}/api";
let buyerMaterials = [];
let isBuyerLoading = false;

document.getElementById('buyerDate').valueAsDate = new Date();

async function loadBuyerProjects() {{
  const sel = document.getElementById('buyerProject');
  try {{
    const resp = await fetch(BUYER_API_URL + '/projects');
    if (!resp.ok) throw new Error('Ошибка сервера ' + resp.status);
    const data = await resp.json();
    sel.innerHTML = '<option value="">-- Выберите проект --</option>';
    data.forEach(p => {{
      sel.innerHTML += `<option value="${{p.id}}">${{p.name}}</option>`;
    }});
  }} catch(e) {{
    sel.innerHTML = `<option value="">Ошибка загрузки: ${{e.message}}</option>`;
  }}
}}

async function onBuyerProjectChange() {{
  const pid = document.getElementById('buyerProject').value;
  document.getElementById('submitBuyerReport').disabled = !pid;
  document.getElementById('buyerItemsContainer').innerHTML = '';
  buyerMaterials = [];

  if (!pid) return;
  isBuyerLoading = true;
  try {{
    const resp = await fetch(BUYER_API_URL + '/projects/' + pid + '/materials');
    if (!resp.ok) throw new Error('Ошибка загрузки материалов');
    buyerMaterials = await resp.json();
  }} catch(e) {{
    console.error('Failed to load buyer materials:', e);
  }} finally {{
    isBuyerLoading = false;
  }}
  addBuyerRow();
}}

function buyerMaterialOptions() {{
  let html = '<option value="">-- Материал --</option>';
  buyerMaterials.forEach((m, i) => {{
    html += `<option value="${{i}}" data-unit="${{m.unit || ''}}" data-plan="${{m.qty_plan ?? ''}}" data-bought="${{m.qty_bought ?? ''}}" data-priceplan="${{m.price_plan ?? ''}}">${{m.name}}</option>`;
  }});
  return html;
}}

function addBuyerRow() {{
  if (isBuyerLoading) return;
  const container = document.getElementById('buyerItemsContainer');
  const row = document.createElement('div');
  row.className = 'dynamic-row';
  row.style.flexWrap = 'wrap';
  row.innerHTML = `
    <div class="field">
      <label>Материал</label>
      <select class="buyer-mat-select" onchange="onBuyerMatSelect(this)">
        ${{buyerMaterialOptions()}}
      </select>
    </div>
    <div class="field-unit buyer-unit" style="padding-top:20px; min-width:50px;"></div>
    <div class="field field-sm">
      <label>Объём</label>
      <input type="number" class="buyer-qty" min="0" step="0.01" placeholder="0" oninput="onBuyerQtyInput(this); updateBuyerCommentState();">
      <div class="buyer-plan-hint" style="font-size:11px;color:#7f8c8d;margin-top:2px;"></div>
    </div>
    <div class="field field-sm">
      <label>Стоимость, ₽</label>
      <input type="number" class="buyer-cost" min="0" step="0.01" placeholder="0" oninput="updateBuyerCommentState()">
      <div class="buyer-price-hint" style="font-size:11px;color:#7f8c8d;margin-top:2px;"></div>
    </div>
    <button type="button" class="remove-btn" onclick="this.parentElement.remove()">×</button>
  `;
  container.appendChild(row);
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

function onBuyerMatSelect(sel) {{
  const row = sel.closest('.dynamic-row');
  const opt = sel.options[sel.selectedIndex];
  row.querySelector('.buyer-unit').textContent = opt.dataset.unit || '';
  const hint = row.querySelector('.buyer-plan-hint');
  const plan = parseFloat(opt.dataset.plan);
  const bought = parseFloat(opt.dataset.bought) || 0;
  if (!isNaN(plan) && plan > 0) {{
    const remaining = Math.max(0, plan - bought);
    hint.textContent = `Осталось купить по плану: ${{remaining.toFixed(2)}}`;
    hint.style.color = '#7f8c8d';
  }} else {{
    hint.textContent = '';
  }}
  onBuyerQtyInput(row.querySelector('.buyer-qty'));
}}

function onBuyerQtyInput(input) {{
  const row = input.closest('.dynamic-row');
  const sel = row.querySelector('.buyer-mat-select');
  const opt = sel ? sel.options[sel.selectedIndex] : null;
  const hint = row.querySelector('.buyer-plan-hint');
  if (!opt) return;
  const plan = parseFloat(opt.dataset.plan);
  const bought = parseFloat(opt.dataset.bought) || 0;
  const qty = parseFloat(input.value) || 0;
  if (!isNaN(plan) && plan > 0) {{
    const newTotal = bought + qty;
    if (newTotal > plan) {{
      const over = (newTotal - plan).toFixed(2);
      input.style.borderColor = '#e74c3c';
      hint.textContent = `⚠ Вы хотите купить на ${{over}} ед. больше плана. Обратитесь к менеджеру.`;
      hint.style.color = '#e74c3c';
    }} else {{
      input.style.borderColor = '';
      const remaining = Math.max(0, plan - bought);
      hint.textContent = `Осталось купить по плану: ${{remaining.toFixed(2)}}`;
      hint.style.color = '#7f8c8d';
    }}
  }}
}}

function _collectBuyerItems() {{
  // Returns {{items, overpriced}} where overpriced[] is material names with price > price_plan.
  const items = [];
  const overpriced = [];
  document.querySelectorAll('#buyerItemsContainer .dynamic-row').forEach(row => {{
    const sel = row.querySelector('.buyer-mat-select');
    if (!sel || sel.value === '') return;
    const idx = parseInt(sel.value);
    const mat = buyerMaterials[idx];
    if (!mat) return;
    const opt = sel.options[sel.selectedIndex];
    const qty = parseFloat(row.querySelector('.buyer-qty').value) || 0;
    const cost = parseFloat(row.querySelector('.buyer-cost').value) || 0;
    if (qty === 0 && cost === 0) return;
    const price = qty > 0 ? cost / qty : 0;
    const pricePlan = parseFloat(opt.dataset.priceplan) || 0;
    if (pricePlan > 0 && price > pricePlan) overpriced.push(mat.name);

    // Render per-row price hint.
    const priceHint = row.querySelector('.buyer-price-hint');
    const costInput = row.querySelector('.buyer-cost');
    if (priceHint && pricePlan > 0 && qty > 0) {{
      const dev = ((price - pricePlan) / pricePlan) * 100;
      if (dev > 0) {{
        const overspend = Math.round((price - pricePlan) * qty);
        priceHint.textContent = `⚠ Цена выше плана на ${{dev.toFixed(1)}}% (+${{overspend}} ₽)`;
        priceHint.style.color = '#c0392b';
        if (costInput) costInput.style.borderColor = '#e74c3c';
      }} else {{
        priceHint.textContent = `План: ${{pricePlan.toFixed(2)}} ₽`;
        priceHint.style.color = '#7f8c8d';
        if (costInput) costInput.style.borderColor = '';
      }}
    }} else if (priceHint && pricePlan > 0) {{
      priceHint.textContent = `План: ${{pricePlan.toFixed(2)}} ₽`;
      priceHint.style.color = '#7f8c8d';
      if (costInput) costInput.style.borderColor = '';
    }} else if (priceHint) {{
      priceHint.textContent = '';
      if (costInput) costInput.style.borderColor = '';
    }}

    items.push({{
      material_name: mat.name,
      unit: mat.unit || '',
      qty: qty,
      price: parseFloat(price.toFixed(4)),
      total: cost,
      price_plan: pricePlan || null,
    }});
  }});
  return {{items, overpriced}};
}}

function updateBuyerCommentState() {{
  const {{overpriced}} = _collectBuyerItems();
  const commentEl = document.getElementById('buyerComment');
  const hintEl = document.getElementById('buyerCommentHint');
  if (overpriced.length > 0) {{
    commentEl.style.borderColor = '#e74c3c';
    hintEl.textContent = '⚠ Цена выше плана для: ' + overpriced.join(', ') +
      '. Обязательно объясните причину повышения.';
    hintEl.style.color = '#c0392b';
  }} else {{
    commentEl.style.borderColor = '';
    hintEl.textContent = '';
  }}
}}

async function submitBuyerReport() {{
  const pid = document.getElementById('buyerProject').value;
  if (!pid) return;

  const proposalFile = document.getElementById('buyerProposal').files[0];
  const buyerComment = (document.getElementById('buyerComment').value || '').trim();
  const errEl = document.getElementById('buyerError');
  errEl.style.display = 'none';

  if (!proposalFile) {{
    errEl.textContent = 'Приложите счёт или коммерческое предложение (PDF).';
    errEl.style.display = 'block';
    return;
  }}

  const {{items, overpriced}} = _collectBuyerItems();
  if (items.length === 0) {{
    errEl.textContent = 'Добавьте хотя бы один материал с ненулевым объёмом или стоимостью.';
    errEl.style.display = 'block';
    return;
  }}
  if (overpriced.length > 0 && !buyerComment) {{
    errEl.textContent = 'Цена выше плана для: ' + overpriced.join(', ') +
      '. Обязательно укажите причину повышения в комментарии.';
    errEl.style.display = 'block';
    document.getElementById('buyerComment').focus();
    return;
  }}

  const btn = document.getElementById('submitBuyerReport');
  btn.disabled = true;
  btn.textContent = 'Отправка...';
  document.getElementById('buyerResult').style.display = 'none';

  try {{
    const fd = new FormData();
    fd.append('project_id', String(parseInt(pid)));
    fd.append('items_json', JSON.stringify(items));
    fd.append('proposal', proposalFile);
    if (buyerComment) fd.append('buyer_comment', buyerComment);

    const resp = await fetch(BUYER_API_URL + '/purchase-request', {{ method: 'POST', body: fd }});
    let data = {{}};
    try {{ data = await resp.json(); }} catch (_) {{}}
    if (!resp.ok) throw new Error(data.detail || 'Ошибка сервера ' + resp.status);

    document.getElementById('buyerItemsContainer').innerHTML = '';
    document.getElementById('buyerProposal').value = '';
    document.getElementById('buyerComment').value = '';
    document.getElementById('buyerCommentHint').textContent = '';
    document.getElementById('buyerProject').value = '';
    document.getElementById('submitBuyerReport').disabled = true;
    buyerMaterials = [];

    document.getElementById('buyerResult').style.display = 'block';
    document.getElementById('buyerResultMsg').textContent =
      `Заявка №${{data.request_no}} отправлена на согласование.`;

    if (typeof BX24 !== 'undefined') BX24.fitWindow();
  }} catch(e) {{
    errEl.style.display = 'block';
    errEl.textContent = 'Ошибка: ' + e.message;
  }} finally {{
    btn.disabled = false;
    btn.textContent = 'Отправить заявку на согласование';
  }}
}}
</script>
"""


def _approval_tab_html() -> str:
    """Согласование tab: list of pending requests + inline approve/reject form."""
    vps_url = settings.vps_url
    return f"""
<h1>Согласование закупок</h1>
<p class="subtitle">Заявки от закупщиков, ожидающие вашего решения</p>

<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
  <button type="button" class="add-btn" onclick="loadPendingRequests()">↻ Обновить</button>
  <span id="approvalStatus" style="font-size:13px;color:#7f8c8d;"></span>
</div>

<div id="approvalList"></div>
<div id="approvalDetail"></div>
<div id="approvalError" style="display:none;margin-top:14px;background:#fdedec;border:1px solid #f5b7b1;border-radius:8px;padding:14px;color:#c0392b;font-size:13px;"></div>

<style>
  .pr-card {{
    background: #fff; border: 1px solid #e0e4e8; border-radius: 10px;
    padding: 12px 14px; margin-bottom: 10px; cursor: pointer;
    transition: border-color .15s, box-shadow .15s;
  }}
  .pr-card:hover {{ border-color: #2980b9; box-shadow: 0 2px 8px rgba(41,128,185,.08); }}
  .pr-card .pr-row {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }}
  .pr-card .pr-num {{ font-weight: 600; color: #2c3e50; }}
  .pr-card .pr-proj {{ color: #7f8c8d; font-size: 13px; }}
  .pr-card .pr-mat {{ font-size: 13px; color: #34495e; margin-top: 4px; }}
  .pr-card .pr-total {{ font-weight: 600; color: #27ae60; }}

  .pr-detail {{ background: #fff; border: 1px solid #e0e4e8; border-radius: 10px; padding: 16px; margin-top: 14px; }}
  .pr-detail h2 {{ font-size: 16px; margin: 0 0 8px 0; }}
  .pr-detail table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin: 8px 0; }}
  .pr-detail th, .pr-detail td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid #ecf0f1; }}
  .pr-detail th {{ background: #f8f9fa; font-weight: 500; }}
  .pr-banner {{
    padding: 10px 12px; border-radius: 6px; margin: 10px 0;
    font-size: 13px; line-height: 1.5; border-left: 4px solid #bdc3c7;
  }}
  .pr-banner.ok {{ background: #eafaf1; border-color: #a9dfbf; }}
  .pr-banner.low {{ background: #fef9e7; border-color: #f7dc6f; }}
  .pr-banner.medium {{ background: #fef5e7; border-color: #f5b041; }}
  .pr-banner.high {{ background: #fdedec; border-color: #e74c3c; }}
  .pr-banner.critical {{ background: #fadbd8; border-color: #922b21; }}
  .pr-banner .pr-banner-emoji {{ font-size: 18px; }}
  .pr-banner .pr-banner-header {{ font-weight: 700; font-size: 14px; margin: 4px 0; }}

  .pr-actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }}
  .pr-actions button {{ flex: 1; min-width: 120px; padding: 10px; color: #fff; border: 0; border-radius: 6px; font-size: 14px; cursor: pointer; }}
  .pr-btn-approve {{ background: #27ae60; }}
  .pr-btn-reject  {{ background: #c0392b; }}
  .pr-btn-comment {{ background: #7f8c8d; }}
  .pr-buyer-comment {{
    background: #eaf4fb; border-left: 4px solid #2980b9;
    padding: 10px 12px; border-radius: 6px; margin: 10px 0; font-size: 13px;
  }}
</style>

<script>
const APPROVAL_API_URL = "{vps_url}";
let approvalSelectedId = null;

async function loadPendingRequests() {{
  const list = document.getElementById('approvalList');
  const detail = document.getElementById('approvalDetail');
  const status = document.getElementById('approvalStatus');
  const errEl = document.getElementById('approvalError');
  errEl.style.display = 'none';
  detail.innerHTML = '';
  approvalSelectedId = null;
  list.innerHTML = '<p style="color:#7f8c8d;font-size:13px;">Загрузка...</p>';
  try {{
    const resp = await fetch(APPROVAL_API_URL + '/api/purchase-requests/pending');
    if (!resp.ok) throw new Error('Ошибка сервера ' + resp.status);
    const items = await resp.json();
    if (items.length === 0) {{
      list.innerHTML = '<p style="color:#7f8c8d;font-size:13px;">Нет заявок, ожидающих согласования.</p>';
      status.textContent = '';
      if (typeof BX24 !== 'undefined') BX24.fitWindow();
      return;
    }}
    status.textContent = `Заявок в ожидании: ${{items.length}}`;
    list.innerHTML = items.map(it => `
      <div class="pr-card" onclick="openRequest(${{it.request_id}})">
        <div class="pr-row">
          <span class="pr-num">№${{it.request_no}} <span class="pr-proj">· ${{escapeHtml(it.project_name)}}</span></span>
          <span class="pr-total">${{(it.total_sum || 0).toFixed(2)}} ₽</span>
        </div>
        <div class="pr-mat">${{escapeHtml(it.material || '—')}} · ${{(it.qty || 0)}} ${{escapeHtml(it.unit || '')}} · ${{escapeHtml(it.author || '—')}}${{it.date ? ' · ' + it.date : ''}}</div>
      </div>
    `).join('');
    if (typeof BX24 !== 'undefined') BX24.fitWindow();
  }} catch (e) {{
    list.innerHTML = '';
    errEl.style.display = 'block';
    errEl.textContent = 'Не удалось загрузить заявки: ' + e.message;
  }}
}}

function escapeHtml(s) {{
  return String(s ?? '').replace(/[&<>"']/g, c => (
    {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]
  ));
}}

async function openRequest(rid) {{
  approvalSelectedId = rid;
  const detail = document.getElementById('approvalDetail');
  const errEl = document.getElementById('approvalError');
  errEl.style.display = 'none';
  detail.innerHTML = '<p style="color:#7f8c8d;font-size:13px;">Загрузка...</p>';
  try {{
    const resp = await fetch(APPROVAL_API_URL + '/api/purchase-requests/' + rid);
    if (!resp.ok) throw new Error('Ошибка сервера ' + resp.status);
    const data = await resp.json();
    detail.innerHTML = renderRequestDetail(data);
    detail.scrollIntoView({{behavior: 'smooth', block: 'start'}});
    if (typeof BX24 !== 'undefined') BX24.fitWindow();
  }} catch (e) {{
    detail.innerHTML = '';
    errEl.style.display = 'block';
    errEl.textContent = 'Не удалось загрузить заявку: ' + e.message;
  }}
}}

function renderRequestDetail(data) {{
  const rows = (data.items || []).map(it => `
    <tr>
      <td>${{escapeHtml(it.material_name)}}</td>
      <td style="text-align:right;">${{(it.qty || 0)}} ${{escapeHtml(it.unit || '')}}</td>
      <td style="text-align:right;">${{(it.price || 0).toFixed(2)}} ₽</td>
      <td style="text-align:right;">${{(it.total || 0).toFixed(2)}} ₽</td>
    </tr>`).join('');

  const banners = (data.items || [])
    .filter(it => it.severity && it.severity.severity && it.severity.severity !== 'none')
    .map(it => {{
      const s = it.severity;
      const headerHtml = s.header ? `<div class="pr-banner-header">${{escapeHtml(s.header)}}</div>` : '';
      return `<div class="pr-banner ${{s.severity}}">
        <div class="pr-banner-emoji">${{s.emoji}}</div>
        ${{headerHtml}}
        <div><b>${{escapeHtml(it.material_name)}}:</b> ${{escapeHtml(s.body)}}</div>
      </div>`;
    }}).join('');

  const buyerCommentHtml = data.comment
    ? `<div class="pr-buyer-comment"><b>💬 Комментарий закупщика:</b><br>${{escapeHtml(data.comment)}}</div>`
    : '';

  const fileHtml = data.file_url
    ? `<p style="margin:8px 0;">📎 <a href="${{escapeHtml(data.file_url)}}" target="_blank">Коммерческое предложение</a></p>`
    : '';

  return `
    <div class="pr-detail">
      <h2>Заявка №${{data.request_no}}</h2>
      <p style="color:#7f8c8d;font-size:13px;margin-bottom:8px;">
        ${{escapeHtml(data.date || '')}} · автор: ${{escapeHtml(data.author || '—')}}
      </p>
      <table>
        <thead><tr><th>Материал</th><th style="text-align:right;">Кол-во</th><th style="text-align:right;">Цена ед.</th><th style="text-align:right;">Сумма</th></tr></thead>
        <tbody>${{rows}}</tbody>
      </table>
      ${{fileHtml}}
      ${{banners}}
      ${{buyerCommentHtml}}
      <label style="display:block;font-size:13px;margin-top:14px;margin-bottom:4px;">Комментарий (необязательно)</label>
      <textarea id="approvalComment" rows="2" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:6px;"></textarea>
      <div class="pr-actions">
        <button class="pr-btn-approve" onclick="decideRequest('approve')">✅ Подтвердить</button>
        <button class="pr-btn-reject"  onclick="decideRequest('reject')">❌ Отклонить</button>
        <button class="pr-btn-comment" onclick="decideRequest('comment')">💬 Только комментарий</button>
      </div>
    </div>`;
}}

async function decideRequest(decision) {{
  if (!approvalSelectedId) return;
  const comment = (document.getElementById('approvalComment').value || '').trim();
  const errEl = document.getElementById('approvalError');
  errEl.style.display = 'none';
  try {{
    const fd = new FormData();
    fd.append('decision', decision);
    if (comment) fd.append('comment', comment);
    const resp = await fetch(APPROVAL_API_URL + '/api/purchase-requests/' + approvalSelectedId + '/decide', {{
      method: 'POST', body: fd,
    }});
    let data = {{}};
    try {{ data = await resp.json(); }} catch (_) {{}}
    if (!resp.ok) throw new Error(data.detail || 'Ошибка сервера ' + resp.status);
    document.getElementById('approvalDetail').innerHTML =
      `<div class="pr-detail" style="text-align:center;color:#27ae60;font-weight:600;">
         Готово — статус: ${{escapeHtml(data.status)}}
       </div>`;
    setTimeout(loadPendingRequests, 600);
  }} catch (e) {{
    errEl.style.display = 'block';
    errEl.textContent = 'Не удалось применить решение: ' + e.message;
  }}
}}
</script>
"""


def _upload_form_html() -> str:
    """Shared upload form HTML used by both install and widget pages."""
    vps_url = settings.vps_url
    # Note: curly braces for JS template literals must be escaped in f-strings
    return f"""
<h1>📊 Импорт Excel</h1>
<p class="subtitle">Загрузите .xlsx файл — проект, списки и задачи будут созданы автоматически в Bitrix24</p>

<div class="form-group">
  <label>Название проекта <span style="color:#7f8c8d;font-weight:400;">(необязательно — по умолчанию имя файла)</span></label>
  <input type="text" id="projectNameInput" placeholder="Например: ЖК Ромашка, корпус 3">
</div>

<div class="upload-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
  <div class="icon">📁</div>
  <p>Нажмите для выбора или перетащите файл <strong>.xlsx</strong> сюда</p>
  <p class="filename" id="fileLabel"></p>
</div>
<input type="file" id="fileInput" accept=".xlsx,.xls">

<button id="importBtn" disabled onclick="startImport()">Импортировать</button>

<div id="progress">
  <p class="progress-title">Идёт импорт, это может занять 30–60 секунд…</p>
  <div class="step" id="step-0"><div class="step-dot"></div> Чтение файла и извлечение данных</div>
  <div class="step" id="step-1"><div class="step-dot"></div> Создание проекта</div>
  <div class="step" id="step-2"><div class="step-dot"></div> Настройка бюджета и материалов</div>
  <div class="step" id="step-3"><div class="step-dot"></div> Создание этапов и задач</div>
  <div class="step" id="step-4"><div class="step-dot"></div> Импорт трудозатрат</div>
</div>

<div id="result">
  <h3>✓ Импорт завершён!</h3>
  <div id="resultStats"></div>
  <div class="links" id="resultLinks"></div>
</div>

<div id="error">
  <strong>Ошибка импорта</strong>
  <span id="errorMsg"></span>
</div>

<script>
const UPLOAD_URL = "{vps_url}/upload";
const STATUS_BASE = "{vps_url}/api/import-status";

const fileInput = document.getElementById('fileInput');
const dropZone  = document.getElementById('dropZone');
const fileLabel = document.getElementById('fileLabel');
const importBtn = document.getElementById('importBtn');
let selectedFile = null;
let progressTimer = null;

fileInput.addEventListener('change', () => {{
  if (fileInput.files.length) selectFile(fileInput.files[0]);
}});

dropZone.addEventListener('dragover', e => {{ e.preventDefault(); dropZone.classList.add('drag'); }});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag'));
dropZone.addEventListener('drop', e => {{
  e.preventDefault();
  dropZone.classList.remove('drag');
  if (e.dataTransfer.files.length) selectFile(e.dataTransfer.files[0]);
}});

function selectFile(file) {{
  selectedFile = file;
  fileLabel.textContent = file.name;
  importBtn.disabled = false;
  hide('result'); hide('error'); hide('progress');
}}

// Approximate durations (ms) for each step before advancing to the next
const STEP_DURATIONS = [3000, 6000, 18000, 18000, 10000];
let currentStep = 0;

function startProgressSteps() {{
  currentStep = 0;
  document.querySelectorAll('.step').forEach(el => {{
    el.classList.remove('active', 'done');
  }});
  activateStep(0);
}}

function activateStep(idx) {{
  const steps = document.querySelectorAll('.step');
  steps.forEach((el, i) => {{
    el.classList.remove('active', 'done');
    if (i < idx) {{
      el.classList.add('done');
      el.querySelector('.step-dot').textContent = '✓';
    }} else {{
      el.querySelector('.step-dot').textContent = '';
    }}
  }});
  if (idx < steps.length) {{
    steps[idx].classList.add('active');
  }}
  if (idx < STEP_DURATIONS.length - 1) {{
    progressTimer = setTimeout(() => activateStep(idx + 1), STEP_DURATIONS[idx]);
  }}
}}

function stopProgressSteps() {{
  if (progressTimer) {{ clearTimeout(progressTimer); progressTimer = null; }}
  // Mark all steps done
  document.querySelectorAll('.step').forEach(el => {{
    el.classList.remove('active');
    el.classList.add('done');
    el.querySelector('.step-dot').textContent = '✓';
  }});
}}

async function startImport() {{
  if (!selectedFile) return;
  importBtn.disabled = true;
  show('progress'); hide('result'); hide('error');
  startProgressSteps();

  const form = new FormData();
  form.append('file', selectedFile);
  const customName = document.getElementById('projectNameInput').value.trim();
  if (customName) form.append('project_name', customName);

  try {{
    // POST returns immediately with a job_id (202 Accepted)
    const resp = await fetch(UPLOAD_URL, {{ method: 'POST', body: form }});
    if (!resp.ok) {{
      let errMsg = 'HTTP ' + resp.status;
      try {{ const e = await resp.json(); errMsg = e.detail || errMsg; }} catch (_) {{}}
      throw new Error(errMsg);
    }}
    const {{ job_id }} = await resp.json();

    // Poll status every 4 seconds until done or error
    const data = await pollImportStatus(job_id);
    stopProgressSteps();
    showResult(data);
  }} catch (e) {{
    stopProgressSteps();
    showError(e.message || String(e));
  }} finally {{
    hide('progress');
    importBtn.disabled = false;
  }}
}}

async function pollImportStatus(jobId) {{
  const POLL_INTERVAL = 4000;
  const MAX_POLLS = 120; // 8 minutes max
  for (let i = 0; i < MAX_POLLS; i++) {{
    await new Promise(r => setTimeout(r, POLL_INTERVAL));
    const resp = await fetch(STATUS_BASE + '/' + jobId);
    if (!resp.ok) throw new Error('Ошибка проверки статуса: HTTP ' + resp.status);
    const job = await resp.json();
    if (job.status === 'done') return job.result;
    if (job.status === 'error') throw new Error(job.error || 'Ошибка импорта');
  }}
  throw new Error('Импорт не завершился за 8 минут. Проверьте сервер.');
}}

function showResult(data) {{
  show('result');
  const stats = document.getElementById('resultStats');
  const listRows = Object.entries(data.lists || {{}})
    .map(([name, count]) => `<div class="stat">• ${{name}}: ${{count}} строк</div>`).join('');
  stats.innerHTML = `
    <div class="stat"><strong>${{data.project_name}}</strong></div>
    ${{listRows}}
    <div class="stat">Создано задач: ${{data.task_count}}</div>
  `;

  const links = document.getElementById('resultLinks');
  const l = data.links || {{}};
  links.innerHTML = '';
  if (l.project) links.innerHTML += mkLink(l.project, 'Открыть проект');
  if (l.lists)   links.innerHTML += mkLink(l.lists,   'Списки');
  if (l.tasks)   links.innerHTML += mkLink(l.tasks,   'Задачи');

  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

function mkLink(url, label) {{
  // Always set href as fallback (target=_top navigates out of the Bitrix
  // iframe to the project page). Try BX24.openPath first — it opens the
  // path inside Bitrix's SPA without a full reload when available.
  let path = url;
  try {{ path = new URL(url).pathname; }} catch(e) {{}}
  const safePath = path.replace(/'/g, "%27");
  const safeUrl = url.replace(/"/g, "&quot;");
  const onclick =
    "try{{if(typeof BX24!=='undefined'&&BX24.openPath){{BX24.openPath('" + safePath + "');return false;}}}}catch(e){{}}" +
    "try{{window.top.location.href='" + safeUrl + "';return false;}}catch(e){{}}return true;";
  return '<a href="' + safeUrl + '" target="_top" onclick="' + onclick + '">' + label + '</a>';
}}

function showError(msg) {{
  show('error');
  document.getElementById('errorMsg').textContent = msg;
  if (typeof BX24 !== 'undefined') BX24.fitWindow();
}}

function show(id) {{ document.getElementById(id).style.display = 'block'; }}
function hide(id) {{ document.getElementById(id).style.display = 'none'; }}
</script>"""
