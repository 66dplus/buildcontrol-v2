/**
 * Typed fetch wrappers for the BuildControl FastAPI backend.
 * All UI data flows through these — no direct Bitrix24 calls from the browser.
 */

export interface WhoAmI {
  user: string;
  role: string;
  host: "standalone" | "bitrix";
  capabilities: string[];
}

export interface Project {
  id: number;
  name: string;
  is_archived: number;
}

export interface BudgetPhase {
  id: number;
  project_id: number;
  phase_name: string;
  bitrix_element_id: string | null;
  materials_plan: number;
  labor_plan: number;
  equipment_plan: number;
  total_plan: number;
  materials_actual: number;
  labor_actual: number;
  equipment_actual: number;
  total_actual: number;
}

export interface TaskRow {
  id: number;
  project_id: number;
  bitrix_task_id: string | null;
  bitrix_element_id: string | null;
  phase: string;
  task_name: string;
  date_start_plan: string | null;
  date_end_plan: string | null;
  date_start_actual: string | null;
  date_end_actual: string | null;
  budget_plan: number;
  budget_actual: number;
  completion_pct: number;
  stage_id: string | null;
  stage_name: string | null;
}

export interface MaterialRow {
  id: number;
  project_id: number;
  phase: string;
  task_name: string;
  material_name: string;
  unit: string;
  price_plan: number;
  qty_plan: number;
  cost_plan: number;
  price_actual: number;
  qty_bought: number;
  qty_consumed: number;
  qty_stock: number;
  cost_actual: number;
}

export interface LaborRow {
  id: number;
  project_id: number;
  phase: string;
  task_name: string;
  specialty: string;
  rate: number;
  hours_plan: number;
  payroll_plan: number;
  hours_actual: number;
  payroll_actual: number;
}

export interface EquipmentRow {
  id: number;
  project_id: number;
  phase: string;
  task_name: string;
  equipment_name: string;
  price_per_hour: number;
  hours_plan: number;
  total_plan: number;
  hours_actual: number;
  total_actual: number;
}

export interface DashboardProject {
  id: number;
  name: string;
  materials_plan: number;
  materials_actual: number;
  labor_plan: number;
  labor_actual: number;
  equipment_plan: number;
  equipment_actual: number;
  total_plan: number;
  total_actual: number;
  variance_pct: number;
  phase_count: number;
  is_behind: boolean;
  expected_by_today: number;
  schedule_variance_abs: number;
  schedule_variance_pct: number;
}

export interface DashboardKpi {
  total_plan: number;
  total_actual: number;
  anomaly_count: number;
  behind_count: number;
}

export interface DashboardSummary {
  projects: DashboardProject[];
  kpi: DashboardKpi;
}

export interface ForemanTask {
  etap: string;
  zadacha: string;
  budget_plan: number;
  element_id: number;
  bitrix_task_id: string | null;
}

export interface ForemanMaterial {
  name: string;
  unit: string;
  stock: number;
  qty_plan: number;
  qty_bought: number;
  price_plan: number;
}

export interface ForemanLabor {
  name: string;
  role: string;
}

export interface ForemanEquipment {
  name: string;
}

export interface Stage {
  id: number;
  title: string;
  sort: number;
  system_type: string | null;
}

export interface Member {
  id: number;
  name: string;
  last_name: string;
}

export interface AssignmentRow {
  phase: string;
  responsible_id: number | null;
  responsible_name: string;
}

export interface AssignPreviewResult {
  assignments: AssignmentRow[];
}

export interface ApplyAssignmentsResult {
  updated: number;
  errors: string[];
}

export interface ImportStatus {
  status: "running" | "done" | "error";
  filename: string;
  result?: {
    project_id: number;
    project_name: string;
    task_count: number;
  };
  error?: string;
}

export interface BudgetTimelinePoint {
  date: string;
  total: number;
  materials?: number;
  labor?: number;
  equipment?: number;
  anomaly?: "red" | "yellow" | "green" | null;
  variance_pct?: number;
}

export interface BudgetTimeline {
  plan_series: Array<{ date: string; total: number }>;
  actual_series: BudgetTimelinePoint[];
}

export interface PurchaseRequest {
  id: string;
  project_id: number;
  status: "pending" | "approved" | "rejected";
  items_json: string;
  buyer_comment: string | null;
  proposal_filename: string | null;
  proposal_path: string | null;
  file_url: string;
  created_at: string;
  resolved_at: string | null;
  actor: string | null;
  approver_comment: string | null;
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

function readBearerToken(): string {
  if (typeof document === "undefined") return "";
  const meta = document.querySelector('meta[name="api-token"]') as HTMLMetaElement | null;
  return meta?.content?.trim() ?? "";
}

async function jsonFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const token = readBearerToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string> | undefined) ?? {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(input, { ...init, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  whoami: () => jsonFetch<WhoAmI>("/api/whoami"),
  projects: () => jsonFetch<Project[]>("/api/projects"),
  dashboardSummary: () => jsonFetch<DashboardSummary>("/api/dashboard/summary"),
  phases: (projectId: number) =>
    jsonFetch<BudgetPhase[]>(`/api/projects/${projectId}/phases`),
  tasks: (projectId: number) =>
    jsonFetch<TaskRow[]>(`/api/projects/${projectId}/tasks-full`),
  materials: (projectId: number, phase?: string, task?: string) =>
    jsonFetch<MaterialRow[]>(
      `/api/projects/${projectId}/materials-all${qs({ phase, task })}`,
    ),
  materialsAll: (projectId: number) =>
    jsonFetch<MaterialRow[]>(`/api/projects/${projectId}/materials-all`),
  labor: (projectId: number, phase?: string, task?: string) =>
    jsonFetch<LaborRow[]>(
      `/api/projects/${projectId}/labor-all${qs({ phase, task })}`,
    ),
  equipment: (projectId: number, phase?: string, task?: string) =>
    jsonFetch<EquipmentRow[]>(
      `/api/projects/${projectId}/equipment-all${qs({ phase, task })}`,
    ),
  purchaseRequestsPending: () =>
    jsonFetch<PurchaseRequest[]>("/api/purchase-requests/pending"),
  decideRequest: (id: number, decision: "approve" | "reject", comment: string) => {
    const token = readBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const body = new FormData();
    body.append("decision", decision);
    body.append("comment", comment);
    return fetch(`/api/purchase-requests/${id}/decide`, {
      method: "POST",
      headers,
      body,
    }).then(async (res) => {
      if (!res.ok) throw new ApiError(res.status, await res.text().catch(() => ""));
      return res.json();
    });
  },
  submitPurchaseRequest: (
    projectId: number,
    items: Array<{ material_name: string; qty: number; unit: string; price: number; price_plan?: number }>,
    proposalFile: File,
    buyerComment: string,
  ) => {
    const token = readBearerToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const body = new FormData();
    body.append("project_id", String(projectId));
    body.append("items_json", JSON.stringify(items));
    body.append("proposal", proposalFile);
    body.append("buyer_comment", buyerComment);
    return fetch("/api/purchase-request", {
      method: "POST",
      headers,
      body,
    }).then(async (res) => {
      if (!res.ok) throw new ApiError(res.status, await res.text().catch(() => ""));
      return res.json() as Promise<{ request_id: string; request_no: string }>;
    });
  },
  budgetTimeline: (projectId: number) =>
    jsonFetch<BudgetTimeline>(`/api/projects/${projectId}/budget-timeline`),
  dashboardBudgetTimeline: () =>
    jsonFetch<BudgetTimeline>("/api/dashboard/budget-timeline"),
  foremanTasks: (projectId: number) =>
    jsonFetch<ForemanTask[]>(`/api/projects/${projectId}/tasks`),
  foremanMaterials: (projectId: number, etap: string, zadacha: string) =>
    jsonFetch<ForemanMaterial[]>(
      `/api/projects/${projectId}/materials${qs({ etap, zadacha })}`,
    ),
  foremanLabor: (projectId: number, etap: string, zadacha: string) =>
    jsonFetch<ForemanLabor[]>(
      `/api/projects/${projectId}/labor${qs({ etap, zadacha })}`,
    ),
  foremanEquipment: (projectId: number, etap: string, zadacha: string) =>
    jsonFetch<ForemanEquipment[]>(
      `/api/projects/${projectId}/equipment${qs({ etap, zadacha })}`,
    ),
  stages: (projectId: number) =>
    jsonFetch<Stage[]>(`/api/projects/${projectId}/stages`),
  submitReport: (body: {
    project_id: number;
    date: string;
    comments: string;
    tasks: Array<{
      task_etap: string;
      task_zadacha: string;
      stage_id?: number;
      materials: Array<{ name: string; quantity: number }>;
      labor: Array<{ name: string; hours: number }>;
      equipment: Array<{ name: string; hours: number }>;
    }>;
  }) =>
    jsonFetch<{ success: boolean; link: string }>("/api/report", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  importStatus: (jobId: string) =>
    jsonFetch<ImportStatus>(`/api/import-status/${jobId}`),
  projectMembers: (projectId: number) =>
    jsonFetch<Member[]>(`/api/projects/${projectId}/members`),
  assignPreview: (
    projectId: number,
    text: string,
    users: Member[],
    phases: string[],
  ) =>
    jsonFetch<AssignPreviewResult>("/api/agent/assign-preview", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, text, users, phases }),
    }),
  applyAssignments: (
    projectId: number,
    assignments: Array<{ phase: string; responsible_id: number }>,
  ) =>
    jsonFetch<ApplyAssignmentsResult>("/api/agent/apply-assignments", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, assignments }),
    }),
};

export { ApiError, jsonFetch };
