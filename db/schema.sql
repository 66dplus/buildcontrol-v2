-- BuildControl SQLite schema
-- SQLite is the primary read DB; Bitrix24 universal lists are kept as a display mirror.

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,   -- = Bitrix workgroup ID
    name TEXT NOT NULL,
    is_archived INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budget_phases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    phase_name TEXT NOT NULL,
    bitrix_element_id TEXT,
    materials_plan REAL DEFAULT 0,
    labor_plan REAL DEFAULT 0,
    equipment_plan REAL DEFAULT 0,
    total_plan REAL DEFAULT 0,
    materials_actual REAL DEFAULT 0,
    labor_actual REAL DEFAULT 0,
    equipment_actual REAL DEFAULT 0,
    total_actual REAL DEFAULT 0,
    UNIQUE(project_id, phase_name)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    bitrix_task_id TEXT,
    bitrix_element_id TEXT,
    phase TEXT NOT NULL,
    task_name TEXT NOT NULL,
    date_start_plan TEXT,
    date_end_plan TEXT,
    date_start_actual TEXT,
    date_end_actual TEXT,
    budget_plan REAL DEFAULT 0,
    budget_actual REAL DEFAULT 0,
    completion_pct REAL DEFAULT 0,
    stage_id TEXT,
    stage_name TEXT,
    UNIQUE(project_id, phase, task_name)
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    bitrix_element_id TEXT,
    phase TEXT NOT NULL,
    task_name TEXT NOT NULL,
    material_name TEXT NOT NULL,
    unit TEXT DEFAULT '',
    price_plan REAL DEFAULT 0,
    qty_plan REAL DEFAULT 0,
    cost_plan REAL DEFAULT 0,
    price_actual REAL DEFAULT 0,
    qty_bought REAL DEFAULT 0,
    qty_consumed REAL DEFAULT 0,
    qty_stock REAL DEFAULT 0,
    cost_actual REAL DEFAULT 0,
    UNIQUE(project_id, phase, task_name, material_name)
);

CREATE TABLE IF NOT EXISTS labor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    bitrix_element_id TEXT,
    phase TEXT NOT NULL,
    task_name TEXT NOT NULL,
    specialty TEXT NOT NULL,
    rate REAL DEFAULT 0,
    hours_plan REAL DEFAULT 0,
    payroll_plan REAL DEFAULT 0,
    hours_actual REAL DEFAULT 0,
    payroll_actual REAL DEFAULT 0,
    UNIQUE(project_id, phase, task_name, specialty)
);

CREATE TABLE IF NOT EXISTS equipment_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    bitrix_element_id TEXT,
    phase TEXT NOT NULL,
    task_name TEXT NOT NULL,
    equipment_name TEXT NOT NULL,
    price_per_hour REAL DEFAULT 0,
    hours_plan REAL DEFAULT 0,
    total_plan REAL DEFAULT 0,
    hours_actual REAL DEFAULT 0,
    total_actual REAL DEFAULT 0,
    UNIQUE(project_id, phase, task_name, equipment_name)
);

CREATE TABLE IF NOT EXISTS purchase_requests (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    bitrix_element_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    items_json TEXT NOT NULL,
    buyer_comment TEXT,
    proposal_filename TEXT,
    proposal_path TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT,
    actor TEXT,
    approver_comment TEXT,
    tg_message_id INTEGER,
    tg_chat_id TEXT,
    file_url TEXT DEFAULT ''   -- Bitrix disk download URL (added via migration)
);

CREATE TABLE IF NOT EXISTS idempotency_cache (
    key TEXT PRIMARY KEY,
    status_code INTEGER NOT NULL DEFAULT 200,
    body_json TEXT NOT NULL,
    stored_at INTEGER NOT NULL
);

-- Indexes for the most common query patterns
CREATE INDEX IF NOT EXISTS idx_materials_project_phase_task
    ON materials(project_id, phase, task_name);
CREATE INDEX IF NOT EXISTS idx_labor_project_phase_task
    ON labor(project_id, phase, task_name);
CREATE INDEX IF NOT EXISTS idx_equipment_project_phase_task
    ON equipment_items(project_id, phase, task_name);
CREATE INDEX IF NOT EXISTS idx_tasks_project
    ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_pr_project_status
    ON purchase_requests(project_id, status);

CREATE TABLE IF NOT EXISTS budget_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    snapshot_date TEXT NOT NULL,   -- YYYY-MM-DD
    mat_actual    REAL DEFAULT 0,
    lab_actual    REAL DEFAULT 0,
    eq_actual     REAL DEFAULT 0,
    total_actual  REAL DEFAULT 0,
    UNIQUE(project_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_project_date
    ON budget_snapshots(project_id, snapshot_date);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id TEXT,
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    result_json TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_session ON audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
