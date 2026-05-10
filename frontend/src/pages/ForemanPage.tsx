import { useEffect, useState } from "react";
import {
  api,
  type ForemanEquipment,
  type ForemanLabor,
  type ForemanMaterial,
  type ForemanTask,
  type Project,
  type Stage,
} from "../lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ResourceRows<T extends { name: string }>({
  items,
  valueKey,
  valueLabel,
  values,
  onChange,
}: {
  items: T[];
  valueKey: string;
  valueLabel: string;
  values: Record<string, number>;
  onChange: (name: string, val: number) => void;
}) {
  if (items.length === 0) return <p className="text-xs text-muted">Нет данных</p>;
  return (
    <div className="space-y-1">
      {items.map((item) => (
        <div key={item.name} className="flex items-center gap-3 text-sm">
          <span className="flex-1 text-ink truncate" title={item.name}>
            {item.name}
          </span>
          <label className="sr-only" htmlFor={`${valueKey}-${item.name}`}>
            {valueLabel}
          </label>
          <input
            id={`${valueKey}-${item.name}`}
            type="number"
            min={0}
            step="any"
            value={values[item.name] ?? ""}
            onChange={(e) => onChange(item.name, parseFloat(e.target.value) || 0)}
            placeholder="0"
            className="w-24 border border-border rounded px-2 py-1 text-xs text-ink bg-bg focus:outline-none focus:border-accent text-right"
          />
          <span className="text-muted text-xs w-8">
            {"unit" in item ? (item as ForemanMaterial).unit : valueKey === "hours" ? "ч" : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

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
// Main page
// ---------------------------------------------------------------------------

export function ForemanPage() {
  // Cascade selectors
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [tasks, setTasks] = useState<ForemanTask[]>([]);
  const [stages, setStages] = useState<Stage[]>([]);
  const [selectedPhase, setSelectedPhase] = useState("");
  const [selectedTask, setSelectedTask] = useState("");
  const [selectedStageId, setSelectedStageId] = useState<number | null>(null);

  // Resource rows
  const [materials, setMaterials] = useState<ForemanMaterial[]>([]);
  const [labor, setLabor] = useState<ForemanLabor[]>([]);
  const [equipment, setEquipment] = useState<ForemanEquipment[]>([]);
  const [matVals, setMatVals] = useState<Record<string, number>>({});
  const [labVals, setLabVals] = useState<Record<string, number>>({});
  const [eqVals, setEqVals] = useState<Record<string, number>>({});

  // Form meta
  const [date, setDate] = useState(today);
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingRows, setLoadingRows] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  // Load projects on mount
  useEffect(() => {
    api.projects().then(setProjects).catch(() => {});
  }, []);

  // Load tasks + stages when project changes
  useEffect(() => {
    if (!selectedProjectId) return;
    setTasks([]);
    setStages([]);
    setSelectedPhase("");
    setSelectedTask("");
    Promise.all([
      api.foremanTasks(selectedProjectId),
      api.stages(selectedProjectId).catch(() => []),
    ]).then(([t, s]) => {
      setTasks(t);
      setStages(s);
    });
  }, [selectedProjectId]);

  // Load resource rows when task is selected
  useEffect(() => {
    if (!selectedProjectId || !selectedPhase || !selectedTask) {
      setMaterials([]);
      setLabor([]);
      setEquipment([]);
      setMatVals({});
      setLabVals({});
      setEqVals({});
      return;
    }
    setLoadingRows(true);
    Promise.all([
      api.foremanMaterials(selectedProjectId, selectedPhase, selectedTask),
      api.foremanLabor(selectedProjectId, selectedPhase, selectedTask),
      api.foremanEquipment(selectedProjectId, selectedPhase, selectedTask).catch(() => []),
    ])
      .then(([m, l, e]) => {
        setMaterials(m);
        setLabor(l);
        setEquipment(e);
        setMatVals({});
        setLabVals({});
        setEqVals({});
      })
      .finally(() => setLoadingRows(false));
  }, [selectedProjectId, selectedPhase, selectedTask]);

  const phases = [...new Set(tasks.map((t) => t.etap))].filter(Boolean);
  const filteredTasks = tasks.filter((t) => t.etap === selectedPhase);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedProjectId || !selectedPhase || !selectedTask) return;
    setError("");
    setLoading(true);

    const body = {
      project_id: selectedProjectId,
      date,
      comments: comment,
      tasks: [
        {
          task_etap: selectedPhase,
          task_zadacha: selectedTask,
          ...(selectedStageId ? { stage_id: selectedStageId } : {}),
          materials: materials
            .map((m) => ({ name: m.name, quantity: matVals[m.name] ?? 0 }))
            .filter((m) => m.quantity > 0),
          labor: labor
            .map((l) => ({ name: l.name, hours: labVals[l.name] ?? 0 }))
            .filter((l) => l.hours > 0),
          equipment: equipment
            .map((eq) => ({ name: eq.name, hours: eqVals[eq.name] ?? 0 }))
            .filter((eq) => eq.hours > 0),
        },
      ],
    };

    try {
      await api.submitReport(body);
      setToast("Сохранено ✓");
      // Reset values after successful submit
      setMatVals({});
      setLabVals({});
      setEqVals({});
      setComment("");
      setSelectedStageId(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const canSubmit =
    !!selectedProjectId && !!selectedPhase && !!selectedTask && !loading;

  return (
    <div className="max-w-2xl mx-auto py-6" data-testid="foreman-page">
      <h1 className="font-heading text-2xl text-ink mb-1">Отчёт прораба</h1>
      <p className="text-muted text-sm mb-6">Заполните ежедневный отчёт по объекту.</p>

      {toast && <Toast message={toast} onDismiss={() => setToast("")} />}

      {error && (
        <div className="mb-4 bg-warning/10 border border-warning text-warning rounded-card px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Cascade selectors */}
        <div className="grid grid-cols-1 gap-3">
          <div>
            <label className="block text-xs font-medium text-muted mb-1">Проект</label>
            <select
              value={selectedProjectId ?? ""}
              onChange={(e) => {
                setSelectedProjectId(e.target.value ? Number(e.target.value) : null);
                setSelectedPhase("");
                setSelectedTask("");
              }}
              data-testid="project-select"
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

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-muted mb-1">Этап</label>
              <select
                value={selectedPhase}
                onChange={(e) => {
                  setSelectedPhase(e.target.value);
                  setSelectedTask("");
                }}
                disabled={!selectedProjectId}
                data-testid="phase-select"
                className="w-full border border-border rounded-card px-3 py-2 text-sm text-ink bg-bg focus:outline-none focus:border-accent disabled:opacity-50"
              >
                <option value="">— этап —</option>
                {phases.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-muted mb-1">Задача</label>
              <select
                value={selectedTask}
                onChange={(e) => setSelectedTask(e.target.value)}
                disabled={!selectedPhase}
                data-testid="task-select"
                className="w-full border border-border rounded-card px-3 py-2 text-sm text-ink bg-bg focus:outline-none focus:border-accent disabled:opacity-50"
              >
                <option value="">— задача —</option>
                {filteredTasks.map((t) => (
                  <option key={t.element_id} value={t.zadacha}>
                    {t.zadacha}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-muted mb-1">Дата</label>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                data-testid="date-input"
                className="w-full border border-border rounded-card px-3 py-2 text-sm text-ink bg-bg focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted mb-1">
                Перевести на этап
              </label>
              <select
                value={selectedStageId ?? ""}
                onChange={(e) =>
                  setSelectedStageId(e.target.value ? Number(e.target.value) : null)
                }
                disabled={stages.length === 0}
                data-testid="stage-select"
                className="w-full border border-border rounded-card px-3 py-2 text-sm text-ink bg-bg focus:outline-none focus:border-accent disabled:opacity-50"
              >
                <option value="">— без изменения —</option>
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Resource rows */}
        {loadingRows && (
          <p className="text-xs text-muted" data-testid="rows-loading">
            Загружаем данные задачи…
          </p>
        )}

        {selectedTask && !loadingRows && (
          <div className="space-y-4 border border-border rounded-card p-4 bg-surface">
            <section>
              <h3 className="text-xs font-medium text-muted uppercase tracking-wide mb-2">
                Материалы — расход
              </h3>
              <ResourceRows
                items={materials}
                valueKey="quantity"
                valueLabel="кол-во"
                values={matVals}
                onChange={(name, val) => setMatVals((prev) => ({ ...prev, [name]: val }))}
              />
            </section>

            <section>
              <h3 className="text-xs font-medium text-muted uppercase tracking-wide mb-2">
                Трудозатраты — ч-часов
              </h3>
              <ResourceRows
                items={labor}
                valueKey="hours"
                valueLabel="часов"
                values={labVals}
                onChange={(name, val) => setLabVals((prev) => ({ ...prev, [name]: val }))}
              />
            </section>

            {equipment.length > 0 && (
              <section>
                <h3 className="text-xs font-medium text-muted uppercase tracking-wide mb-2">
                  Техника — часов
                </h3>
                <ResourceRows
                  items={equipment}
                  valueKey="hours"
                  valueLabel="часов"
                  values={eqVals}
                  onChange={(name, val) => setEqVals((prev) => ({ ...prev, [name]: val }))}
                />
              </section>
            )}
          </div>
        )}

        {/* Comment */}
        <div>
          <label className="block text-xs font-medium text-muted mb-1">
            Комментарий (необязательно)
          </label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            data-testid="comment-input"
            placeholder="Замечания, отклонения, особые обстоятельства…"
            className="w-full border border-border rounded-card px-3 py-2 text-sm text-ink bg-bg focus:outline-none focus:border-accent resize-none"
          />
        </div>

        <button
          type="submit"
          disabled={!canSubmit}
          data-testid="submit-btn"
          className="w-full bg-accent text-white text-sm font-medium rounded-pill py-3 hover:bg-accent/90 disabled:opacity-50"
        >
          {loading ? "Сохраняется…" : "Отправить отчёт"}
        </button>
      </form>
    </div>
  );
}
