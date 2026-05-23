import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";

interface TaskDraft {
  id: string;
  name: string;
  date_start_plan: string;
  date_end_plan: string;
  budget_plan: string;
}

interface PhaseDraft {
  id: string;
  name: string;
  materials_plan: string;
  labor_plan: string;
  equipment_plan: string;
  tasks: TaskDraft[];
}

let _idSeq = 0;
const nextId = () => `${Date.now()}_${++_idSeq}`;

function newTask(): TaskDraft {
  return { id: nextId(), name: "", date_start_plan: "", date_end_plan: "", budget_plan: "" };
}

function newPhase(): PhaseDraft {
  return {
    id: nextId(),
    name: "",
    materials_plan: "",
    labor_plan: "",
    equipment_plan: "",
    tasks: [newTask()],
  };
}

function num(v: string): number {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

export function CreateProjectPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [phases, setPhases] = useState<PhaseDraft[]>([newPhase()]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updatePhase = (id: string, patch: Partial<PhaseDraft>) =>
    setPhases((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)));

  const updateTask = (phaseId: string, taskId: string, patch: Partial<TaskDraft>) =>
    setPhases((prev) =>
      prev.map((p) =>
        p.id === phaseId
          ? { ...p, tasks: p.tasks.map((t) => (t.id === taskId ? { ...t, ...patch } : t)) }
          : p,
      ),
    );

  const submit = async () => {
    setError(null);
    if (!name.trim()) {
      setError("Введите название проекта");
      return;
    }
    setSubmitting(true);
    try {
      const result = await api.createProject({
        name: name.trim(),
        phases: phases
          .filter((p) => p.name.trim())
          .map((p) => ({
            name: p.name.trim(),
            materials_plan: num(p.materials_plan),
            labor_plan: num(p.labor_plan),
            equipment_plan: num(p.equipment_plan),
            tasks: p.tasks
              .filter((t) => t.name.trim())
              .map((t) => ({
                name: t.name.trim(),
                date_start_plan: t.date_start_plan || undefined,
                date_end_plan: t.date_end_plan || undefined,
                budget_plan: num(t.budget_plan),
              })),
          })),
      });
      navigate(`/projects/${result.project_id}`);
    } catch (e) {
      setError((e as Error).message || "Не удалось создать проект");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-5 max-w-3xl" data-testid="create-project">
      <div>
        <h1 className="font-heading text-xl md:text-2xl text-ink">Новый проект</h1>
        <p className="text-muted text-sm">
          Заполните основные параметры. Этапы и задачи можно добавить сразу или позже.
        </p>
      </div>

      <div className="bg-surface border border-border rounded-card p-5 shadow-card flex flex-col gap-3">
        <label className="block">
          <span className="block text-xs font-medium text-muted mb-1">Название проекта</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="напр. ЖК «Северный» — корпус 3"
            className="w-full border border-border rounded-card px-3 py-2 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
            data-testid="project-name-input"
          />
        </label>
      </div>

      {/* Phases */}
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="font-heading text-lg text-ink">Этапы и задачи</h2>
          <button
            type="button"
            onClick={() => setPhases((prev) => [...prev, newPhase()])}
            className="text-accent text-sm hover:underline"
          >
            + Добавить этап
          </button>
        </div>

        {phases.map((p, idx) => (
          <div
            key={p.id}
            className="bg-surface border border-border rounded-card p-4 shadow-card flex flex-col gap-3"
            data-testid={`phase-${idx}`}
          >
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <label className="block">
                  <span className="block text-xs font-medium text-muted mb-1">
                    Этап #{idx + 1}
                  </span>
                  <input
                    type="text"
                    value={p.name}
                    onChange={(e) => updatePhase(p.id, { name: e.target.value })}
                    placeholder="напр. Фундаментные работы"
                    className="w-full border border-border rounded-card px-2 py-2 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
                  />
                </label>
              </div>
              {phases.length > 1 && (
                <button
                  type="button"
                  onClick={() => setPhases((prev) => prev.filter((x) => x.id !== p.id))}
                  className="text-muted hover:text-warning text-xl leading-none mt-5"
                  aria-label="Удалить этап"
                >
                  ×
                </button>
              )}
            </div>

            <div className="grid grid-cols-3 gap-3">
              <label className="block">
                <span className="block text-[11px] text-muted mb-1">Материалы план, ₽</span>
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={p.materials_plan}
                  onChange={(e) => updatePhase(p.id, { materials_plan: e.target.value })}
                  className="w-full border border-border rounded-card px-2 py-1.5 text-sm bg-bg text-ink focus:outline-none focus:border-accent text-right"
                />
              </label>
              <label className="block">
                <span className="block text-[11px] text-muted mb-1">ФОТ план, ₽</span>
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={p.labor_plan}
                  onChange={(e) => updatePhase(p.id, { labor_plan: e.target.value })}
                  className="w-full border border-border rounded-card px-2 py-1.5 text-sm bg-bg text-ink focus:outline-none focus:border-accent text-right"
                />
              </label>
              <label className="block">
                <span className="block text-[11px] text-muted mb-1">Техника план, ₽</span>
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={p.equipment_plan}
                  onChange={(e) => updatePhase(p.id, { equipment_plan: e.target.value })}
                  className="w-full border border-border rounded-card px-2 py-1.5 text-sm bg-bg text-ink focus:outline-none focus:border-accent text-right"
                />
              </label>
            </div>

            {/* Tasks within phase */}
            <div className="border-t border-border pt-3 flex flex-col gap-2">
              <div className="text-xs font-medium text-muted">Задачи</div>
              {p.tasks.map((t, tIdx) => (
                <div
                  key={t.id}
                  className="grid grid-cols-[1.4fr_1fr_1fr_1fr_auto] gap-2 items-center"
                >
                  <input
                    type="text"
                    value={t.name}
                    onChange={(e) => updateTask(p.id, t.id, { name: e.target.value })}
                    placeholder={`Задача #${tIdx + 1} (напр. Заливка плиты)`}
                    className="border border-border rounded-card px-2 py-1.5 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
                  />
                  <input
                    type="date"
                    value={t.date_start_plan}
                    onChange={(e) =>
                      updateTask(p.id, t.id, { date_start_plan: e.target.value })
                    }
                    className="border border-border rounded-card px-2 py-1.5 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
                  />
                  <input
                    type="date"
                    value={t.date_end_plan}
                    onChange={(e) =>
                      updateTask(p.id, t.id, { date_end_plan: e.target.value })
                    }
                    className="border border-border rounded-card px-2 py-1.5 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
                  />
                  <input
                    type="number"
                    min={0}
                    step="any"
                    value={t.budget_plan}
                    onChange={(e) =>
                      updateTask(p.id, t.id, { budget_plan: e.target.value })
                    }
                    placeholder="Бюджет, ₽"
                    className="border border-border rounded-card px-2 py-1.5 text-sm bg-bg text-ink focus:outline-none focus:border-accent text-right"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      updatePhase(p.id, {
                        tasks: p.tasks.filter((x) => x.id !== t.id),
                      })
                    }
                    disabled={p.tasks.length === 1}
                    className="text-muted hover:text-warning text-lg leading-none disabled:opacity-30"
                    aria-label="Удалить задачу"
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() =>
                  updatePhase(p.id, { tasks: [...p.tasks, newTask()] })
                }
                className="text-accent text-xs hover:underline self-start mt-1"
              >
                + Добавить задачу
              </button>
            </div>
          </div>
        ))}
      </div>

      {error && (
        <div className="text-warning text-sm bg-warning/10 border border-warning/40 rounded-card px-3 py-2">
          {error}
        </div>
      )}

      <div className="flex gap-3 sticky bottom-0 bg-bg/90 backdrop-blur py-3">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="border border-border text-ink text-sm rounded-pill px-5 py-2 hover:bg-bg"
        >
          Отмена
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={submitting}
          className="bg-accent text-white text-sm font-medium rounded-pill px-6 py-2 hover:bg-accent/90 disabled:opacity-50"
          data-testid="create-project-submit"
        >
          {submitting ? "Создаём…" : "Создать проект"}
        </button>
      </div>
    </div>
  );
}
