import type { TaskRow } from "../../../lib/api";
import { formatDate, formatMoney, formatPercent, variancePct } from "../../../lib/format";

interface TaskDetailPanelProps {
  task: TaskRow;
  onBack?: () => void;
}

export function TaskDetailPanel({ task, onBack }: TaskDetailPanelProps) {
  const v = variancePct(task.budget_plan, task.budget_actual);
  return (
    <div className="flex flex-col gap-4" data-testid="task-detail-panel">
      {onBack ? (
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-muted hover:text-ink self-start"
          data-testid="task-back"
        >
          ← К списку задач
        </button>
      ) : null}

      <div>
        <div className="text-xs text-muted uppercase tracking-wide mb-1">
          {task.phase}
        </div>
        <h3 className="text-lg font-heading text-ink">{task.task_name}</h3>
        {task.stage_name ? (
          <span className="inline-block mt-2 text-xs px-2 py-1 rounded-pill border border-border bg-bg text-muted">
            {task.stage_name}
          </span>
        ) : null}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted">Бюджет план</dt>
        <dd className="text-right tabular text-ink">{formatMoney(task.budget_plan, { compact: true })}</dd>
        <dt className="text-muted">Бюджет факт</dt>
        <dd className="text-right tabular text-ink">{formatMoney(task.budget_actual, { compact: true })}</dd>
        <dt className="text-muted">Отклонение</dt>
        <dd className={`text-right tabular font-medium ${v > 15 ? "text-warning" : "text-ink"}`}>
          {v > 0 ? "+" : ""}
          {formatPercent(v, 1)}
        </dd>
        <dt className="text-muted">Готовность</dt>
        <dd className="text-right tabular text-ink">{formatPercent(task.completion_pct)}</dd>
      </dl>

      <div className="border-t border-border pt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted">Старт план</dt>
        <dd className="text-right text-ink">{formatDate(task.date_start_plan)}</dd>
        <dt className="text-muted">Старт факт</dt>
        <dd className="text-right text-ink">{formatDate(task.date_start_actual)}</dd>
        <dt className="text-muted">Финиш план</dt>
        <dd className="text-right text-ink">{formatDate(task.date_end_plan)}</dd>
        <dt className="text-muted">Финиш факт</dt>
        <dd className="text-right text-ink">{formatDate(task.date_end_actual)}</dd>
      </div>
    </div>
  );
}
