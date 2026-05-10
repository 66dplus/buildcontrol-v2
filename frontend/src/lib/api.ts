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
}

export interface DashboardKpi {
  total_plan: number;
  total_actual: number;
  anomaly_count: number;
}

export interface DashboardSummary {
  projects: DashboardProject[];
  kpi: DashboardKpi;
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
  labor: (projectId: number, phase?: string, task?: string) =>
    jsonFetch<LaborRow[]>(
      `/api/projects/${projectId}/labor-all${qs({ phase, task })}`,
    ),
  equipment: (projectId: number, phase?: string, task?: string) =>
    jsonFetch<EquipmentRow[]>(
      `/api/projects/${projectId}/equipment-all${qs({ phase, task })}`,
    ),
  purchaseRequestsPending: () =>
    jsonFetch<PurchaseRequest[]>("/api/purchase-requests?status=pending"),
  patchPurchaseRequest: (
    id: string,
    body: { decision: "approve" | "reject"; comment?: string },
  ) =>
    jsonFetch<PurchaseRequest>(`/api/purchase-requests/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};

export { ApiError, jsonFetch };
