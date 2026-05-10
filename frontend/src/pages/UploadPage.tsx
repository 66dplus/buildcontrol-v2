import { useRef, useState } from "react";
import { api, type AssignmentRow, type Member } from "../lib/api";

type UploadStep = "idle" | "uploading" | "polling" | "assigning" | "applying" | "done";

interface JobResult {
  project_id: number;
  project_name: string;
  task_count: number;
}

interface PhaseAssignment {
  phase: string;
  responsible_id: number | null;
  responsible_name: string;
}

export function UploadPage() {
  const [step, setStep] = useState<UploadStep>("idle");
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState("");
  const [jobResult, setJobResult] = useState<JobResult | null>(null);
  const [assignText, setAssignText] = useState("");
  const [members, setMembers] = useState<Member[]>([]);
  const [phases, setPhases] = useState<string[]>([]);
  const [assignments, setAssignments] = useState<PhaseAssignment[]>([]);
  const [applyResult, setApplyResult] = useState<{ updated: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleErr(msg: string) {
    setError(msg);
    setStep("idle");
  }

  async function startUpload(file: File) {
    setError("");
    setStep("uploading");

    const formData = new FormData();
    formData.append("file", file);

    let res: Response;
    try {
      res = await fetch("/upload", { method: "POST", body: formData });
    } catch (e) {
      return handleErr(`Ошибка сети: ${(e as Error).message}`);
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return handleErr(text || `HTTP ${res.status}`);
    }
    const { job_id } = await res.json();
    setJobId(job_id);
    setStep("polling");
    pollStatus(job_id);
  }

  function pollStatus(id: string) {
    pollRef.current = setTimeout(async () => {
      try {
        const status = await api.importStatus(id);
        if (status.status === "running") {
          pollStatus(id);
          return;
        }
        if (status.status === "error") {
          return handleErr(status.error ?? "Ошибка импорта");
        }
        // done
        const result = status.result!;
        setJobResult(result);
        // Load members + phases in parallel
        const [membersData, tasksData] = await Promise.all([
          api.projectMembers(result.project_id).catch(() => [] as Member[]),
          api.tasks(result.project_id).catch(() => []),
        ]);
        setMembers(membersData);
        const uniquePhases = [...new Set(tasksData.map((t) => t.phase))].filter(Boolean);
        setPhases(uniquePhases);
        setStep("assigning");
      } catch (e) {
        handleErr((e as Error).message);
      }
    }, 2000);
  }

  async function runAssignPreview() {
    if (!jobResult || !assignText.trim()) return;
    setError("");
    try {
      const result = await api.assignPreview(
        jobResult.project_id,
        assignText,
        members,
        phases,
      );
      setAssignments(result.assignments as PhaseAssignment[]);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function updateAssignment(phase: string, responsibleId: number | null) {
    setAssignments((prev) =>
      prev.map((a) =>
        a.phase === phase
          ? {
              ...a,
              responsible_id: responsibleId,
              responsible_name:
                members.find((m) => m.id === responsibleId)
                  ? `${members.find((m) => m.id === responsibleId)!.name} ${members.find((m) => m.id === responsibleId)!.last_name}`.trim()
                  : a.responsible_name,
            }
          : a,
      ),
    );
  }

  async function applyAssignments() {
    if (!jobResult || assignments.length === 0) return;
    setStep("applying");
    try {
      const valid = assignments.filter((a) => a.responsible_id !== null) as Array<{
        phase: string;
        responsible_id: number;
      }>;
      const result = await api.applyAssignments(jobResult.project_id, valid);
      setApplyResult({ updated: result.updated });
      setStep("done");
    } catch (e) {
      setError((e as Error).message);
      setStep("assigning");
    }
  }

  function skipAssignment() {
    setStep("done");
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) startUpload(file);
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) startUpload(file);
  }

  return (
    <div className="max-w-2xl mx-auto py-6" data-testid="upload-page">
      <h1 className="font-heading text-2xl text-ink mb-1">Загрузка проекта</h1>
      <p className="text-muted text-sm mb-6">
        Загрузите Excel-файл (шаблон v3) и распределите ответственных по этапам.
      </p>

      {error && (
        <div
          className="mb-4 bg-warning/10 border border-warning text-warning rounded-card px-4 py-3 text-sm"
          data-testid="upload-error"
        >
          {error}
        </div>
      )}

      {/* Step 1 — drag-drop */}
      {(step === "idle" || step === "uploading") && (
        <div
          className={`border-2 border-dashed rounded-card-lg p-10 text-center cursor-pointer transition-colors ${
            dragging ? "border-accent bg-accent/5" : "border-border hover:border-accent/60"
          }`}
          data-testid="drop-zone"
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={handleFileChange}
            data-testid="file-input"
          />
          {step === "uploading" ? (
            <p className="text-muted text-sm" data-testid="uploading-msg">Загружается…</p>
          ) : (
            <>
              <p className="text-ink text-sm font-medium mb-1">
                Перетащите .xlsx сюда или нажмите для выбора
              </p>
              <p className="text-muted text-xs">Шаблон Excel v3 — до 50 МБ</p>
            </>
          )}
        </div>
      )}

      {/* Step 2 — polling */}
      {step === "polling" && (
        <div className="rounded-card border border-border p-6 text-center" data-testid="polling-msg">
          <p className="text-sm text-muted mb-2">Импорт запущен (job: {jobId})</p>
          <p className="text-xs text-muted">Создаём проект и листы в Bitrix24…</p>
          <div className="mt-4 h-1 w-48 mx-auto bg-border rounded-full overflow-hidden">
            <div className="h-full bg-accent animate-pulse w-full" />
          </div>
        </div>
      )}

      {/* Step 3 — NL assignment */}
      {step === "assigning" && jobResult && (
        <div className="space-y-4" data-testid="assign-step">
          <div className="rounded-card border border-border p-4 bg-surface">
            <p className="text-sm font-medium text-ink mb-1">
              Проект импортирован: <span className="text-accent">{jobResult.project_name}</span>
            </p>
            <p className="text-xs text-muted">{jobResult.task_count} задач создано</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-ink mb-2">
              Распределение ответственных (на русском)
            </label>
            <textarea
              value={assignText}
              onChange={(e) => setAssignText(e.target.value)}
              placeholder='Например: "Алексея Петрова на этапы 1–3, Андрея на Каркас"'
              rows={3}
              data-testid="assign-textarea"
              className="w-full border border-border rounded-card px-3 py-2 text-sm text-ink bg-bg focus:outline-none focus:border-accent resize-none"
            />
            <button
              type="button"
              onClick={runAssignPreview}
              disabled={!assignText.trim()}
              data-testid="preview-btn"
              className="mt-2 bg-accent text-white text-sm font-medium rounded-pill px-4 py-2 hover:bg-accent/90 disabled:opacity-50"
            >
              Разобрать
            </button>
          </div>

          {assignments.length > 0 && (
            <div data-testid="assign-table">
              <p className="text-sm font-medium text-ink mb-2">Предварительный просмотр</p>
              <div className="border border-border rounded-card overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-bg border-b border-border">
                    <tr>
                      <th className="text-left px-3 py-2 text-muted font-medium">Этап</th>
                      <th className="text-left px-3 py-2 text-muted font-medium">Ответственный</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assignments.map((a) => (
                      <tr key={a.phase} className="border-b border-border last:border-0">
                        <td className="px-3 py-2 text-ink">{a.phase}</td>
                        <td className="px-3 py-2">
                          <select
                            value={a.responsible_id ?? ""}
                            onChange={(e) =>
                              updateAssignment(
                                a.phase,
                                e.target.value ? Number(e.target.value) : null,
                              )
                            }
                            className="border border-border rounded text-xs px-1 py-0.5 bg-bg text-ink"
                          >
                            <option value="">— не назначен —</option>
                            {members.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.name} {m.last_name} (ID:{m.id})
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex gap-2 mt-4">
                <button
                  type="button"
                  onClick={applyAssignments}
                  data-testid="apply-btn"
                  className="bg-accent text-white text-sm font-medium rounded-pill px-5 py-2 hover:bg-accent/90"
                >
                  Применить
                </button>
                <button
                  type="button"
                  onClick={skipAssignment}
                  data-testid="skip-btn"
                  className="text-muted text-sm hover:text-ink px-3 py-2"
                >
                  Пропустить
                </button>
              </div>
            </div>
          )}

          {assignments.length === 0 && (
            <button
              type="button"
              onClick={skipAssignment}
              data-testid="skip-btn"
              className="text-muted text-sm hover:text-ink"
            >
              Пропустить распределение →
            </button>
          )}
        </div>
      )}

      {/* Step 4 — applying */}
      {step === "applying" && (
        <div className="rounded-card border border-border p-6 text-center" data-testid="applying-msg">
          <p className="text-sm text-muted">Применяем назначения в Bitrix24…</p>
        </div>
      )}

      {/* Step 5 — done */}
      {step === "done" && (
        <div className="rounded-card border border-border p-6 text-center space-y-2" data-testid="done-msg">
          <p className="text-ink font-medium text-sm">
            {applyResult
              ? `Готово — обновлено ${applyResult.updated} задач`
              : "Импорт завершён"}
          </p>
          {jobResult && (
            <p className="text-xs text-muted">
              Проект <span className="text-accent">{jobResult.project_name}</span> (ID:{" "}
              {jobResult.project_id})
            </p>
          )}
          <button
            type="button"
            onClick={() => {
              setStep("idle");
              setJobId("");
              setJobResult(null);
              setAssignments([]);
              setAssignText("");
              setApplyResult(null);
            }}
            data-testid="upload-again-btn"
            className="mt-2 text-accent text-sm hover:underline"
          >
            Загрузить ещё один проект
          </button>
        </div>
      )}
    </div>
  );
}
