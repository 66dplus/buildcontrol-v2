import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type MaterialRow, type Project, type PurchaseRequest } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LineItem {
  id: number;
  material_name: string;
  qty: number;
  unit: string;
  price: number;
  price_plan: number;
}

let _lineId = 0;
function newLine(): LineItem {
  return { id: ++_lineId, material_name: "", qty: 1, unit: "шт", price: 0, price_plan: 0 };
}

// ---------------------------------------------------------------------------
// Sub: Toast
// ---------------------------------------------------------------------------

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 3500);
    return () => clearTimeout(t);
  }, [onDismiss]);
  return (
    <div
      className="fixed bottom-6 right-6 z-50 bg-ink text-white text-sm font-medium rounded-card px-4 py-3 shadow-card"
      data-testid="toast"
    >
      {message}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub: Submit purchase request tab
// ---------------------------------------------------------------------------

function SubmitTab({ projects }: { projects: Project[] }) {
  const [projectId, setProjectId] = useState<number | null>(null);
  const [lines, setLines] = useState<LineItem[]>([newLine()]);
  const [comment, setComment] = useState("");
  const [proposalFile, setProposalFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [catalog, setCatalog] = useState<MaterialRow[]>([]);

  useEffect(() => {
    if (!projectId) { setCatalog([]); return; }
    api.materialsAll(projectId).then(setCatalog).catch(() => setCatalog([]));
  }, [projectId]);

  const catalogMaterials = useMemo(() => {
    const seen = new Set<string>();
    return catalog.filter((m) => {
      if (seen.has(m.material_name)) return false;
      seen.add(m.material_name);
      return true;
    });
  }, [catalog]);

  const overPlanNames = lines
    .filter((l) => l.price_plan > 0 && l.price > l.price_plan)
    .map((l) => l.material_name || "?");
  const commentRequired = overPlanNames.length > 0;

  function updateLine(id: number, patch: Partial<LineItem>) {
    setLines((prev) => prev.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  }

  function dropFile(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f && f.type === "application/pdf") setProposalFile(f);
    else setError("Допускаются только PDF-файлы");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!projectId || !proposalFile) return;
    if (commentRequired && !comment.trim()) {
      setError(`Комментарий обязателен (превышение плана): ${overPlanNames.join(", ")}`);
      return;
    }
    setError("");
    setLoading(true);
    try {
      const items = lines
        .filter((l) => l.material_name.trim())
        .map((l) => ({
          material_name: l.material_name,
          qty: l.qty,
          unit: l.unit,
          price: l.price,
          price_plan: l.price_plan || undefined,
        }));
      const result = await api.submitPurchaseRequest(projectId, items, proposalFile, comment);
      setToast(`Заявка №${result.request_no} отправлена`);
      setLines([newLine()]);
      setComment("");
      setProposalFile(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div data-testid="submit-tab">
      {toast && <Toast message={toast} onDismiss={() => setToast("")} />}
      {error && (
        <div className="mb-4 bg-warning/10 border border-warning text-warning rounded-card px-4 py-3 text-sm">
          {error}
        </div>
      )}
      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-xs font-medium text-muted mb-1">Проект</label>
          <select
            value={projectId ?? ""}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}
            data-testid="pr-project-select"
            className="w-full border border-border rounded-card px-3 py-2 text-sm text-ink bg-bg focus:outline-none focus:border-accent"
          >
            <option value="">— выберите проект —</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {/* Line items */}
        <div>
          <div className="grid grid-cols-[1fr_60px_60px_80px_80px_24px] gap-2 text-xs text-muted mb-1 px-1">
            <span>Материал</span>
            <span>Кол-во</span>
            <span>Ед.</span>
            <span>Цена</span>
            <span>План</span>
            <span />
          </div>
          {lines.map((line) => (
            <div
              key={line.id}
              className={`grid grid-cols-[1fr_60px_60px_80px_80px_24px] gap-2 mb-1 ${
                line.price_plan > 0 && line.price > line.price_plan ? "bg-warning/5 rounded" : ""
              }`}
            >
              <select
                value={line.material_name}
                onChange={(e) => {
                  const mat = catalogMaterials.find((m) => m.material_name === e.target.value);
                  updateLine(line.id, { material_name: e.target.value });
                  if (mat?.price_plan) updateLine(line.id, { price_plan: mat.price_plan });
                }}
                className="w-full border border-border rounded-card px-2 py-1.5 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
              >
                <option value="">— выбрать материал —</option>
                {catalogMaterials.map((m) => (
                  <option key={m.material_name} value={m.material_name}>
                    {m.material_name} ({m.unit})
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={0}
                step="any"
                value={line.qty}
                onChange={(e) => updateLine(line.id, { qty: parseFloat(e.target.value) || 0 })}
                className="border border-border rounded px-2 py-1 text-xs text-ink bg-bg text-right"
              />
              <input
                type="text"
                value={line.unit}
                onChange={(e) => updateLine(line.id, { unit: e.target.value })}
                className="border border-border rounded px-2 py-1 text-xs text-ink bg-bg"
              />
              <input
                type="number"
                min={0}
                step="any"
                value={line.price}
                onChange={(e) => updateLine(line.id, { price: parseFloat(e.target.value) || 0 })}
                placeholder="₽"
                className="border border-border rounded px-2 py-1 text-xs text-ink bg-bg text-right"
              />
              <input
                type="number"
                min={0}
                step="any"
                value={line.price_plan}
                onChange={(e) =>
                  updateLine(line.id, { price_plan: parseFloat(e.target.value) || 0 })
                }
                placeholder="план"
                className="border border-border rounded px-2 py-1 text-xs text-muted bg-bg text-right"
              />
              <button
                type="button"
                onClick={() => setLines((prev) => prev.filter((l) => l.id !== line.id))}
                className="text-muted hover:text-warning text-sm leading-none"
                aria-label="Удалить строку"
              >
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setLines((prev) => [...prev, newLine()])}
            className="text-accent text-xs mt-1 hover:underline"
            data-testid="add-line-btn"
          >
            + Добавить позицию
          </button>
        </div>

        {/* PDF upload */}
        <div>
          <label className="block text-xs font-medium text-muted mb-1">
            Коммерческое предложение (PDF)
          </label>
          <div
            className={`border-2 border-dashed rounded-card p-4 text-center cursor-pointer ${
              dragging ? "border-accent bg-accent/5" : "border-border hover:border-accent/60"
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={dropFile}
            onClick={() => fileInputRef.current?.click()}
            data-testid="pdf-dropzone"
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) setProposalFile(f);
              }}
            />
            <p className="text-sm text-muted">
              {proposalFile ? proposalFile.name : "Перетащите PDF или нажмите"}
            </p>
          </div>
        </div>

        {/* Comment */}
        <div>
          <label className="block text-xs font-medium text-muted mb-1">
            Комментарий{commentRequired ? " (обязательно — превышение плана)" : ""}
          </label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            data-testid="pr-comment"
            placeholder="Обоснование цены, условия поставщика…"
            className="w-full border border-border rounded-card px-3 py-2 text-sm text-ink bg-bg focus:outline-none focus:border-accent resize-none"
          />
        </div>

        <button
          type="submit"
          disabled={!projectId || !proposalFile || loading}
          data-testid="pr-submit-btn"
          className="w-full bg-accent text-white text-sm font-medium rounded-pill py-3 hover:bg-accent/90 disabled:opacity-50"
        >
          {loading ? "Отправляется…" : "Отправить заявку"}
        </button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub: Pending approvals tab
// ---------------------------------------------------------------------------

function ApprovalsTab() {
  const [requests, setRequests] = useState<PurchaseRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [comments, setComments] = useState<Record<string, string>>({});
  const [toast, setToast] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    api
      .purchaseRequestsPending()
      .then(setRequests)
      .catch(() => setRequests([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function decide(req: PurchaseRequest, decision: "approve" | "reject") {
    setDeciding(req.id);
    try {
      await api.decideRequest(Number(req.id), decision, comments[req.id] ?? "");
      setToast(decision === "approve" ? "Заявка одобрена" : "Заявка отклонена");
      load();
    } catch (err) {
      setToast(`Ошибка: ${(err as Error).message}`);
    } finally {
      setDeciding(null);
    }
  }

  if (loading)
    return <p className="text-muted text-sm" data-testid="approvals-loading">Загружаем…</p>;

  return (
    <div data-testid="approvals-tab">
      {toast && <Toast message={toast} onDismiss={() => setToast("")} />}
      {requests.length === 0 ? (
        <p className="text-muted text-sm">Нет заявок на рассмотрении</p>
      ) : (
        <div className="space-y-4">
          {requests.map((req) => (
            <div
              key={req.id}
              className="border border-border rounded-card p-4 bg-surface"
              data-testid="approval-card"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-ink">Заявка #{req.id}</span>
                <span className="text-xs text-muted">{req.created_at?.slice(0, 10)}</span>
              </div>
              {req.buyer_comment && (
                <p className="text-xs text-muted mb-2 italic">«{req.buyer_comment}»</p>
              )}
              {req.file_url && (
                <a
                  href={req.file_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-accent hover:underline block mb-3"
                >
                  КП → открыть PDF
                </a>
              )}
              <textarea
                value={comments[req.id] ?? ""}
                onChange={(e) =>
                  setComments((prev) => ({ ...prev, [req.id]: e.target.value }))
                }
                rows={1}
                placeholder="Комментарий согласующего (необязательно)"
                className="w-full border border-border rounded px-2 py-1 text-xs text-ink bg-bg mb-2 focus:outline-none focus:border-accent resize-none"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={deciding === req.id}
                  onClick={() => decide(req, "approve")}
                  data-testid="approve-btn"
                  className="flex-1 bg-accent text-white text-xs font-medium rounded-pill py-2 hover:bg-accent/90 disabled:opacity-50"
                >
                  Одобрить
                </button>
                <button
                  type="button"
                  disabled={deciding === req.id}
                  onClick={() => decide(req, "reject")}
                  data-testid="reject-btn"
                  className="flex-1 bg-warning/10 border border-warning text-warning text-xs font-medium rounded-pill py-2 hover:bg-warning/20 disabled:opacity-50"
                >
                  Отклонить
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function ProcurementPage() {
  const [tab, setTab] = useState<"submit" | "approvals">("submit");
  const [projects, setProjects] = useState<Project[]>([]);

  useEffect(() => {
    api.projects().then(setProjects).catch(() => {});
  }, []);

  return (
    <div className="max-w-2xl mx-auto py-6" data-testid="procurement-page">
      <h1 className="font-heading text-2xl text-ink mb-1">Закупки</h1>
      <p className="text-muted text-sm mb-5">Заявки на закупку и их согласование.</p>

      {/* Pill tabs */}
      <div className="flex gap-1 p-1 bg-bg border border-border rounded-pill mb-6 w-fit">
        {(["submit", "approvals"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            data-testid={`tab-${t}`}
            className={`text-sm px-4 py-1.5 rounded-pill transition-colors ${
              tab === t
                ? "bg-surface text-ink font-medium shadow-card"
                : "text-muted hover:text-ink"
            }`}
          >
            {t === "submit" ? "Подать заявку" : "На согласовании"}
          </button>
        ))}
      </div>

      {tab === "submit" && <SubmitTab projects={projects} />}
      {tab === "approvals" && <ApprovalsTab />}
    </div>
  );
}
