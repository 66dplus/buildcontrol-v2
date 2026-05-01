"""
BuildControl shared UI styles — Procore-inspired design system.

Single source of truth for visual styling across every HTML surface returned
by the FastAPI app. Importing modules concatenate ``BASE_CSS`` (or call the
helper functions) into their inline ``<style>`` and ``<head>`` blocks.

Design tokens, palette, typography, components, and the mobile breakpoint
mirror ``.stitch/DESIGN.md`` — keep the two in sync if you tweak anything.

There are no static assets, no templating engine, no new dependencies; the
deploy story (rsync + systemctl restart) stays unchanged.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Fonts: pulled from Google Fonts CDN at request time. IBM Plex Sans for body
# (engineering / blueprint character that suits a construction tool) and IBM
# Plex Mono for tabular numerics. System stack fallback covers offline iframes.
# ---------------------------------------------------------------------------

FONT_LINKS: str = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=IBM+Plex+Sans:wght@400;500;600;700&"
    "family=IBM+Plex+Mono:wght@500;600&display=swap"
    '" rel="stylesheet">'
)


# ---------------------------------------------------------------------------
# Core stylesheet. Restyles every selector used by the existing markup
# (.tab-bar, .form-group, .dynamic-row, .task-block, .upload-zone, #submitReport,
# #importBtn, #progress, .step, #result, #error, .card, etc.) and adds new
# Procore-style utility classes (.bc-*) for KPI tiles, status pills, severity
# banners, responsive tables, and the mobile sticky action bar.
# ---------------------------------------------------------------------------

BASE_CSS: str = """<style>
:root {
  --bc-primary: #F47E42;
  --bc-primary-hover: #E76A2C;
  --bc-primary-soft: #FFF1E8;
  --bc-ink: #1B2733;
  --bc-ink-muted: #5C6B7A;
  --bc-ink-subtle: #8A95A1;
  --bc-surface: #FFFFFF;
  --bc-surface-alt: #F8F9FB;
  --bc-bg: #F4F5F7;
  --bc-border: #E1E4E8;
  --bc-border-strong: #C7CDD3;
  --bc-success: #1F8A4C;
  --bc-success-soft: #E6F4EC;
  --bc-warning: #E0A100;
  --bc-warning-soft: #FFF6DA;
  --bc-danger: #C0392B;
  --bc-danger-soft: #FCE8E5;
  --bc-info: #2C6EAD;
  --bc-info-soft: #E6EFF7;
  --bc-shadow-1: 0 1px 2px rgba(27,39,51,0.06), 0 1px 3px rgba(27,39,51,0.08);
  --bc-shadow-2: 0 8px 24px rgba(27,39,51,0.12);
  --bc-radius-card: 12px;
  --bc-radius-input: 6px;
  --bc-font-body: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  --bc-font-mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  font-family: var(--bc-font-body);
  font-size: 14px;
  line-height: 1.5;
  color: var(--bc-ink);
  background: var(--bc-bg);
  padding: 24px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ---- Typography ---- */
h1 { font-size: 28px; line-height: 36px; font-weight: 600; letter-spacing: -0.01em; margin-bottom: 4px; }
h2 { font-size: 20px; line-height: 28px; font-weight: 600; letter-spacing: -0.01em; }
h3 { font-size: 16px; line-height: 24px; font-weight: 600; }
.subtitle { color: var(--bc-ink-muted); font-size: 14px; margin-bottom: 24px; }
.bc-label, .form-group label, .dynamic-row .field label,
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--bc-ink-muted);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.section-title {
  margin: 24px 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--bc-border);
  color: var(--bc-ink);
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
a { color: var(--bc-info); text-decoration: none; }
a:hover { text-decoration: underline; }

/* numeric font for money / qty values */
.bc-num, .dynamic-row input[type="number"], td.bc-num,
.task-block input[type="number"] {
  font-family: var(--bc-font-mono);
  font-variant-numeric: tabular-nums;
}

/* ---- Tab bar (desktop pill nav) ---- */
.tab-bar {
  display: flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 24px;
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: 999px;
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
}
.tab-btn {
  padding: 8px 18px;
  border: 0;
  background: transparent;
  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  color: var(--bc-ink-muted);
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 150ms ease, color 150ms ease;
}
.tab-btn:hover { background: var(--bc-surface-alt); color: var(--bc-ink); }
.tab-btn.active {
  background: var(--bc-primary-soft);
  color: var(--bc-primary);
  font-weight: 600;
}
.tab-content { display: none; }

/* ---- Form fields ---- */
.form-group { margin-bottom: 20px; }
.form-group > label {
  display: block;
  margin-bottom: 8px;
  color: var(--bc-ink);
}
.form-group select,
.form-group input[type="text"],
.form-group input[type="number"],
.form-group input[type="date"],
.form-group textarea {
  width: 100%;
  height: 40px;
  padding: 0 12px;
  font-family: inherit;
  font-size: 14px;
  color: var(--bc-ink);
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-input);
  transition: border-color 150ms ease, box-shadow 150ms ease;
}
.form-group textarea {
  height: auto;
  min-height: 88px;
  padding: 10px 12px;
  resize: vertical;
}
.form-group select:focus,
.form-group input:focus,
.form-group textarea:focus,
.dynamic-row .field input:focus,
.dynamic-row .field select:focus,
.task-block-header select:focus {
  outline: 0;
  border-color: var(--bc-primary);
  box-shadow: 0 0 0 3px rgba(244, 126, 66, 0.18);
}

/* ---- Dynamic line-item rows (materials, labor, equipment) ---- */
.dynamic-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 8px;
  padding: 12px;
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: 10px;
}
.dynamic-row .field { flex: 1; min-width: 0; }
.dynamic-row .field-sm { flex: 0 0 90px; }
.dynamic-row .field-unit {
  flex: 0 0 60px;
  font-size: 13px;
  color: var(--bc-ink-muted);
  padding-top: 19px;
}
.dynamic-row .field label {
  display: block;
  margin-bottom: 4px;
  font-size: 11px;
}
.dynamic-row .field select,
.dynamic-row .field input {
  width: 100%;
  height: 36px;
  padding: 0 10px;
  font-family: inherit;
  font-size: 13px;
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-input);
  background: var(--bc-surface);
}
.dynamic-row .remove-btn {
  flex: 0 0 32px;
  height: 32px;
  margin-top: 19px;
  align-self: flex-start;
  border: 1px solid var(--bc-border);
  background: var(--bc-surface);
  color: var(--bc-danger);
  border-radius: var(--bc-radius-input);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  transition: background-color 150ms ease, border-color 150ms ease;
}
.dynamic-row .remove-btn:hover { background: var(--bc-danger-soft); border-color: var(--bc-danger); }

/* ---- Add buttons ---- */
.add-btn,
.add-task-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 16px;
  border: 1px dashed var(--bc-border-strong);
  border-radius: var(--bc-radius-input);
  background: transparent;
  color: var(--bc-primary);
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease;
}
.add-task-btn { display: block; width: 100%; padding: 12px; margin-bottom: 16px; }
.add-btn:hover,
.add-task-btn:hover {
  border-color: var(--bc-primary);
  background: var(--bc-primary-soft);
}

/* ---- Task block (per-task report card) ---- */
.task-block {
  position: relative;
  margin-bottom: 16px;
  padding: 16px;
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-card);
}
.task-block-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.task-block-header label {
  font-size: 12px;
  font-weight: 600;
  color: var(--bc-ink-muted);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}
.task-block-header select {
  flex: 1;
  height: 36px;
  padding: 0 10px;
  font-family: inherit;
  font-size: 14px;
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-input);
  background: var(--bc-surface-alt);
}
.task-block-remove {
  flex: 0 0 32px;
  height: 32px;
  border: 1px solid var(--bc-border);
  background: var(--bc-surface);
  color: var(--bc-danger);
  border-radius: var(--bc-radius-input);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}
.task-block-remove:hover { background: var(--bc-danger-soft); border-color: var(--bc-danger); }
.task-block .section-title {
  font-size: 11px;
  margin: 14px 0 8px;
  padding-bottom: 6px;
  letter-spacing: 0.06em;
}

/* ---- Primary submit buttons (foreman, buyer, import) ---- */
button#submitReport,
button#submitBuyerReport,
button#importBtn {
  width: 100%;
  height: 48px;
  margin-top: 20px;
  padding: 0 16px;
  font-family: inherit;
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  background: var(--bc-primary);
  border: 0;
  border-radius: var(--bc-radius-input);
  cursor: pointer;
  transition: background-color 150ms ease, transform 100ms ease, box-shadow 200ms ease;
}
button#submitReport:hover:not(:disabled),
button#submitBuyerReport:hover:not(:disabled),
button#importBtn:hover:not(:disabled) {
  background: var(--bc-primary-hover);
  box-shadow: var(--bc-shadow-1);
}
button#submitReport:active:not(:disabled),
button#submitBuyerReport:active:not(:disabled),
button#importBtn:active:not(:disabled) { transform: translateY(1px); }
button#submitReport:disabled,
button#submitBuyerReport:disabled,
button#importBtn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ---- Result / error blocks ---- */
#result,
#reportResult,
#buyerResult {
  display: none;
  margin-top: 20px;
  padding: 16px 16px 16px 20px;
  background: var(--bc-success-soft);
  border-left: 4px solid var(--bc-success);
  border-radius: var(--bc-radius-card);
}
#result h3,
#reportResult h3,
#buyerResult h3 { font-size: 15px; color: var(--bc-success); margin-bottom: 8px; }
#result .stat,
#reportResult p,
#buyerResult p { font-size: 13px; color: var(--bc-ink); margin: 4px 0; }
#result .links { margin-top: 12px; }
#result .links a {
  display: inline-block;
  margin: 4px 6px 4px 0;
  padding: 6px 12px;
  background: var(--bc-surface);
  color: var(--bc-ink);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-input);
  font-size: 13px;
  font-weight: 500;
}
#result .links a:hover { border-color: var(--bc-primary); color: var(--bc-primary); text-decoration: none; }

#error,
#reportError,
#buyerError {
  display: none;
  margin-top: 20px;
  padding: 14px 16px 14px 20px;
  background: var(--bc-danger-soft);
  border-left: 4px solid var(--bc-danger);
  border-radius: var(--bc-radius-card);
  color: var(--bc-danger);
  font-size: 13px;
}
#error strong { display: block; margin-bottom: 4px; font-size: 14px; color: var(--bc-danger); }

/* ---- Upload dropzone ---- */
.upload-zone {
  position: relative;
  padding: 40px 24px;
  text-align: center;
  background: var(--bc-surface);
  border: 2px dashed var(--bc-border-strong);
  border-radius: var(--bc-radius-card);
  cursor: pointer;
  transition: border-color 150ms ease, background-color 150ms ease;
  margin-bottom: 16px;
}
.upload-zone:hover,
.upload-zone.drag {
  border-color: var(--bc-primary);
  background: var(--bc-primary-soft);
}
.upload-zone .icon { font-size: 36px; margin-bottom: 10px; color: var(--bc-primary); }
.upload-zone p { color: var(--bc-ink-muted); font-size: 14px; }
.upload-zone .filename { color: var(--bc-primary); font-weight: 600; font-size: 14px; margin-top: 8px; }
.upload-zone input[type=file] { display: none; }

/* ---- Compact file picker (PDF attachment in buyer form) ---- */
.file-pick-zone {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 44px;
  padding: 0 14px;
  background: var(--bc-surface);
  border: 1px dashed var(--bc-border-strong);
  border-radius: var(--bc-radius-input);
  cursor: pointer;
  transition: border-color 150ms ease, background-color 150ms ease;
  color: var(--bc-ink-muted);
  font-size: 13px;
  user-select: none;
}
.file-pick-zone:hover {
  border-color: var(--bc-primary);
  background: var(--bc-primary-soft);
  color: var(--bc-primary);
}
.file-pick-zone.has-file {
  border-color: var(--bc-success);
  background: var(--bc-success-soft);
  color: var(--bc-success);
}
.file-pick-zone .fpz-icon { font-size: 16px; flex-shrink: 0; }
.file-pick-zone .fpz-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-pick-zone input[type=file] { display: none; }

/* ---- Progress steps ---- */
#progress { display: none; margin-top: 20px; }
#progress .progress-title {
  font-size: 12px;
  color: var(--bc-ink-muted);
  text-align: center;
  margin-bottom: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.step {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin: 4px 0;
  font-size: 14px;
  color: var(--bc-ink-subtle);
  background: transparent;
  border-radius: var(--bc-radius-input);
  transition: background-color 200ms ease, color 200ms ease;
}
.step.active {
  color: var(--bc-primary);
  background: var(--bc-primary-soft);
  font-weight: 500;
}
.step.done { color: var(--bc-success); }
.step-dot {
  width: 18px; height: 18px;
  border-radius: 50%;
  background: var(--bc-border);
  display: flex; align-items: center; justify-content: center;
  font-size: 11px;
  flex-shrink: 0;
  transition: all 200ms ease;
}
.step.active .step-dot {
  border: 2px solid var(--bc-primary);
  border-top-color: transparent;
  background: transparent;
  animation: bc-spin .8s linear infinite;
}
.step.done .step-dot { background: var(--bc-success); color: #fff; font-size: 12px; }
@keyframes bc-spin { to { transform: rotate(360deg); } }

/* ---- New utility components (used by approval pages + new screens) ---- */
.bc-page {
  max-width: 760px;
  margin: 0 auto;
}
.bc-stack > * + * { margin-top: 16px; }
.bc-card {
  padding: 20px;
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-card);
}
.bc-card + .bc-card { margin-top: 16px; }
.bc-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.bc-card-header h2 { font-size: 16px; }

.bc-meta {
  color: var(--bc-ink-muted);
  font-size: 13px;
  margin-bottom: 16px;
}

.bc-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 22px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  border-radius: 999px;
  background: var(--bc-surface-alt);
  color: var(--bc-ink-muted);
  border: 1px solid var(--bc-border);
  white-space: nowrap;
}
.bc-pill--success { background: var(--bc-success-soft); color: var(--bc-success); border-color: transparent; }
.bc-pill--warn    { background: var(--bc-warning-soft); color: var(--bc-warning); border-color: transparent; }
.bc-pill--danger  { background: var(--bc-danger-soft);  color: var(--bc-danger);  border-color: transparent; }
.bc-pill--info    { background: var(--bc-info-soft);    color: var(--bc-info);    border-color: transparent; }

.bc-banner {
  position: relative;
  padding: 14px 16px 14px 20px;
  background: var(--bc-info-soft);
  border-left: 4px solid var(--bc-info);
  border-radius: var(--bc-radius-card);
  font-size: 14px;
  line-height: 1.5;
  color: var(--bc-ink);
}
.bc-banner + .bc-banner { margin-top: 12px; }
.bc-banner__icon { display: block; font-size: 20px; line-height: 1; margin-bottom: 6px; }
.bc-banner__title { font-weight: 600; margin-bottom: 4px; }
.bc-banner--info    { background: var(--bc-info-soft);    border-left-color: var(--bc-info); }
.bc-banner--success { background: var(--bc-success-soft); border-left-color: var(--bc-success); }
.bc-banner--warn    { background: var(--bc-warning-soft); border-left-color: var(--bc-warning); }
.bc-banner--danger  { background: var(--bc-danger-soft);  border-left-color: var(--bc-danger); }

.bc-tile {
  padding: 16px;
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-card);
}
.bc-tile__label {
  font-size: 11px;
  font-weight: 600;
  color: var(--bc-ink-muted);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.bc-tile__value {
  margin-top: 6px;
  font-family: var(--bc-font-mono);
  font-size: 24px;
  font-weight: 600;
  color: var(--bc-ink);
  font-variant-numeric: tabular-nums;
}

/* ---- Buttons (new component, used on approval page) ---- */
.bc-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 40px;
  padding: 0 16px;
  font-family: inherit;
  font-size: 14px;
  font-weight: 600;
  border-radius: var(--bc-radius-input);
  border: 1px solid transparent;
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease, transform 100ms ease, box-shadow 200ms ease;
  text-decoration: none;
}
.bc-btn:active:not(:disabled) { transform: translateY(1px); }
.bc-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.bc-btn--primary   { background: var(--bc-primary); color: #fff; }
.bc-btn--primary:hover:not(:disabled)   { background: var(--bc-primary-hover); box-shadow: var(--bc-shadow-1); }
.bc-btn--secondary { background: var(--bc-surface); color: var(--bc-ink); border-color: var(--bc-border-strong); }
.bc-btn--secondary:hover:not(:disabled) { border-color: var(--bc-ink-muted); }
.bc-btn--ghost     { background: transparent; color: var(--bc-ink-muted); }
.bc-btn--ghost:hover:not(:disabled)     { background: var(--bc-surface-alt); color: var(--bc-ink); }
.bc-btn--success   { background: var(--bc-success); color: #fff; }
.bc-btn--success:hover:not(:disabled)   { background: #15703B; box-shadow: var(--bc-shadow-1); }
.bc-btn--danger    { background: var(--bc-danger); color: #fff; }
.bc-btn--danger:hover:not(:disabled)    { background: #9F2E22; box-shadow: var(--bc-shadow-1); }
.bc-btn-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
}
.bc-btn-row .bc-btn { flex: 1; min-width: 140px; height: 44px; }

/* ---- Tables ---- */
.bc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
.bc-table thead th {
  position: sticky;
  top: 0;
  padding: 10px 12px;
  background: var(--bc-surface-alt);
  color: var(--bc-ink-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  text-align: left;
  border-bottom: 1px solid var(--bc-border);
}
.bc-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--bc-border);
  color: var(--bc-ink);
}
.bc-table tbody tr:hover td { background: var(--bc-surface-alt); }
.bc-table tfoot td {
  padding: 12px;
  font-weight: 600;
  border-top: 1px solid var(--bc-border);
}
.bc-table .num { text-align: right; font-family: var(--bc-font-mono); font-variant-numeric: tabular-nums; }

/* ---- Approval list / pending request cards (rendered by JS) ---- */
.pr-card {
  padding: 14px 16px;
  margin-bottom: 10px;
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-left: 4px solid var(--bc-warning);
  border-radius: var(--bc-radius-card);
  cursor: pointer;
  transition: border-color 150ms ease, box-shadow 200ms ease, transform 100ms ease;
}
.pr-card:hover { border-color: var(--bc-primary); box-shadow: var(--bc-shadow-1); }
.pr-card.selected { border-color: var(--bc-primary); border-left-color: var(--bc-primary); background: var(--bc-primary-soft); }
.pr-card .pr-title { font-size: 14px; font-weight: 600; color: var(--bc-ink); margin-bottom: 4px; }
.pr-card .pr-meta { font-size: 12px; color: var(--bc-ink-muted); }
.pr-detail { padding: 16px; }

/* ---- Sticky-style "approval status" pill in the approval tab header ---- */
#approvalStatus { font-size: 13px; color: var(--bc-ink-muted); }

/* ---- Reduced motion ---- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}

/* =====================================================================
   Mobile (< 768px): tabs collapse to bottom nav, tables stack as cards,
   primary buttons become a sticky bottom action bar, inputs grow to 44px.
   ===================================================================== */
@media (max-width: 768px) {
  body { padding: 16px 16px 96px; }
  h1 { font-size: 22px; line-height: 28px; }
  h2 { font-size: 18px; }

  .tab-bar {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    z-index: 50;
    width: 100%;
    max-width: none;
    margin: 0;
    padding: 8px 12px calc(8px + env(safe-area-inset-bottom, 0px));
    border-radius: 0;
    border: 0;
    border-top: 1px solid var(--bc-border);
    background: var(--bc-surface);
    box-shadow: 0 -4px 16px rgba(27,39,51,0.06);
    justify-content: space-around;
    overflow-x: visible;
  }
  .tab-btn { padding: 8px 10px; font-size: 12px; flex: 1; }

  .form-group select,
  .form-group input[type="text"],
  .form-group input[type="number"],
  .form-group input[type="date"] { height: 44px; font-size: 16px; }
  .form-group textarea { font-size: 16px; }

  .dynamic-row { flex-wrap: wrap; }
  .dynamic-row .field { flex: 1 1 100%; }
  .dynamic-row .field-sm { flex: 1 1 calc(50% - 5px); }
  .dynamic-row .field-unit { flex: 0 0 auto; }
  .dynamic-row .field input,
  .dynamic-row .field select { height: 44px; font-size: 16px; }

  button#submitReport,
  button#submitBuyerReport,
  button#importBtn {
    position: sticky;
    bottom: calc(70px + env(safe-area-inset-bottom, 0px));
    height: 52px;
    box-shadow: var(--bc-shadow-2);
  }

  .bc-btn-row { flex-direction: column; }
  .bc-btn-row .bc-btn { width: 100%; }

  /* Responsive table: each row becomes a stacked card with data-label rows */
  .bc-table--responsive thead { display: none; }
  .bc-table--responsive,
  .bc-table--responsive tbody,
  .bc-table--responsive tr,
  .bc-table--responsive td { display: block; width: 100%; }
  .bc-table--responsive tr {
    margin-bottom: 8px;
    padding: 12px;
    background: var(--bc-surface);
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-radius-card);
  }
  .bc-table--responsive tbody tr:hover td { background: transparent; }
  .bc-table--responsive td {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 6px 0;
    border-bottom: 0;
    text-align: left !important;
  }
  .bc-table--responsive td::before {
    content: attr(data-label);
    color: var(--bc-ink-muted);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    flex-shrink: 0;
  }
  .bc-table--responsive tfoot tr { border-color: var(--bc-primary); }
  .bc-table--responsive tfoot td { border-top: 0; }
}
</style>"""


# ---------------------------------------------------------------------------
# Small HTML fragment helpers. Used where the existing inline-string layout
# has hand-rolled status colors / banners; a single helper means future tone
# changes happen in one place.
# ---------------------------------------------------------------------------

_PILL_VARIANTS = {
    "success": "bc-pill bc-pill--success",
    "warn":    "bc-pill bc-pill--warn",
    "danger":  "bc-pill bc-pill--danger",
    "info":    "bc-pill bc-pill--info",
    "neutral": "bc-pill",
}


def status_pill(text: str, variant: str = "neutral") -> str:
    """Render a status pill. ``variant`` ∈ success | warn | danger | info | neutral."""
    cls = _PILL_VARIANTS.get(variant, "bc-pill")
    return f'<span class="{cls}">{text}</span>'


def severity_banner(*, variant: str, icon: str = "", title: str = "", body: str = "") -> str:
    """Render a severity banner with optional icon, bold title, and body copy."""
    icon_html = f'<span class="bc-banner__icon">{icon}</span>' if icon else ""
    title_html = f'<div class="bc-banner__title">{title}</div>' if title else ""
    return (
        f'<div class="bc-banner bc-banner--{variant}">'
        f'{icon_html}{title_html}<div>{body}</div>'
        f'</div>'
    )
