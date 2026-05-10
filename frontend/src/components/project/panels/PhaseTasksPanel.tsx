import { useState } from "react";
import type { TaskRow } from "../../../lib/api";
import { formatMoney, formatPercent, variancePct } from "../../../lib/format";
import { TaskDetailPanel } from "./TaskDetailPanel";

interface PhaseTasksPanelProps {
  phaseName: string;
  tasks: TaskRow[];
}

export function PhaseTasksPanel({ phaseName, tasks }: PhaseTasksPanelProps) {
  const [selected, setSelected] = useState<TaskRow | null>(null);

  if (selected) {
    return <TaskDetailPanel task={selected} onBack={() => setSelected(null)} />;
  }

  const totalPlan = tasks.reduce((s, t) => s + t.budget_plan, 0);
  const totalActual = tasks.reduce((s, t) => s + t.budget_actual, 0);

  return (
    <div className="flex flex-col gap-4" data-testid="phase-tasks-panel">
      <div>
        <div className="text-xs text-muted uppercase tracking-wide mb-1">Этап</div>
        <h3 className="text-lg font-heading text-ink">{phaseName}</h3>
        <div className="text-sm text-muted mt-1">
          {tasks.length} {tasks.length === 1 ? "задача" : "задач(и)"} ·{" "}
          {formatMoney(totalPlan, { compact: true })} план /{" "}
          {formatMoney(totalActual, { compact: true })} факт
        </div>
      </div>

      <ul className="flex flex-col gap-2">
        {tasks.map((t) => {
          const v = variancePct(t.budget_plan, t.budget_actual);
          return (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => setSelected(t)}
                data-testid={`task-${t.id}`}
                className="w-full text-left bg-bg border border-border rounded-card px-3 py-3 hover:border-accent transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-ink font-medium text-sm">{t.task_name}</span>
                  {t.stage_name ? (
                    <span className="text-xs px-2 py-0.5 rounded-pill border border-border bg-surface text-muted whitespace-nowrap">
                      {t.stage_name}
                    </span>
                  ) : null}
                </div>
                <div className="flex items-center justify-between text-xs text-muted mt-1">
                  <span>{formatPercent(t.completion_pct)} готово</span>
                  <span className="tabular flex items-center gap-2">
                    <span>План: {formatMoney(t.budget_plan, { compact: true })}</span>
                    {v !== 0 && (
                      <span className={v > 15 ? "text-warning font-medium" : v > 0 ? "text-muted" : "text-accent"}>
                        {v > 0 ? "+" : ""}{formatMoney(t.budget_actual - t.budget_plan, { compact: true })} ({v > 0 ? "+" : ""}{formatPercent(v, 1)})
                      </span>
                    )}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
