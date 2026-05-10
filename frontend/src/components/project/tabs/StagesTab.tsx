import { useMemo } from "react";
import type { TaskRow } from "../../../lib/api";
import { formatMoney, formatPercent, variancePct } from "../../../lib/format";
import { useSidePanel } from "../../../contexts/SidePanelContext";
import { PhaseTasksPanel } from "../panels/PhaseTasksPanel";

interface StagesTabProps {
  tasks: TaskRow[];
}

interface PhaseSummary {
  name: string;
  taskCount: number;
  avgCompletion: number;
  totalPlan: number;
  totalActual: number;
  tasks: TaskRow[];
}

export function buildPhaseSummaries(tasks: TaskRow[]): PhaseSummary[] {
  const groups = new Map<string, TaskRow[]>();
  for (const t of tasks) {
    const arr = groups.get(t.phase) ?? [];
    arr.push(t);
    groups.set(t.phase, arr);
  }
  return Array.from(groups.entries())
    .map(([name, items]) => ({
      name,
      taskCount: items.length,
      avgCompletion:
        items.length > 0
          ? items.reduce((s, t) => s + t.completion_pct, 0) / items.length
          : 0,
      totalPlan: items.reduce((s, t) => s + t.budget_plan, 0),
      totalActual: items.reduce((s, t) => s + t.budget_actual, 0),
      tasks: items,
    }))
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
}

export function StagesTab({ tasks }: StagesTabProps) {
  const phases = useMemo(() => buildPhaseSummaries(tasks), [tasks]);
  const { openPanel } = useSidePanel();

  if (phases.length === 0) {
    return (
      <div
        className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center"
        data-testid="stages-empty"
      >
        Нет задач в этом проекте
      </div>
    );
  }

  return (
    <div
      className="bg-surface border border-border rounded-card overflow-hidden shadow-card"
      data-testid="stages-tab"
    >
      <table className="w-full text-sm">
        <thead className="bg-bg border-b border-border text-muted text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Этап</th>
            <th className="px-4 py-3 text-right font-medium">Задач</th>
            <th className="px-4 py-3 text-right font-medium">Готовность</th>
            <th className="px-4 py-3 text-right font-medium">Бюджет план/факт</th>
            <th className="px-4 py-3 text-right font-medium">Откл.</th>
          </tr>
        </thead>
        <tbody>
          {phases.map((p) => {
            const v = variancePct(p.totalPlan, p.totalActual);
            const overrun = v > 15;
            return (
              <tr
                key={p.name}
                onClick={() =>
                  openPanel(<PhaseTasksPanel phaseName={p.name} tasks={p.tasks} />)
                }
                data-testid={`stage-row-${p.name}`}
                className={`border-b border-border last:border-0 hover:bg-bg cursor-pointer transition-colors ${
                  overrun ? "border-l-4 border-l-warning" : ""
                }`}
              >
                <td className="px-4 py-3 text-ink font-medium">{p.name}</td>
                <td className="px-4 py-3 text-right tabular text-ink">
                  {p.taskCount}
                </td>
                <td className="px-4 py-3 text-right tabular text-ink">
                  {formatPercent(p.avgCompletion)}
                </td>
                <td className="px-4 py-3 text-right tabular">
                  <div className="text-muted">{formatMoney(p.totalPlan, { compact: true })}</div>
                  <div className="text-ink font-medium">
                    {formatMoney(p.totalActual, { compact: true })}
                  </div>
                </td>
                <td
                  className={`px-4 py-3 text-right tabular font-medium ${
                    overrun ? "text-warning" : "text-ink"
                  }`}
                >
                  {v > 0 ? "+" : ""}
                  {formatPercent(v, 1)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
