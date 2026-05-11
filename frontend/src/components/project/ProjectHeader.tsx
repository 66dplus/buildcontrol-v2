import { Link } from "react-router-dom";
import { formatMoney, formatPercent } from "../../lib/format";

export interface ProjectHeaderTotals {
  total_plan: number;
  total_actual: number;
  variance_pct: number;
  completion_pct: number;
}

interface ProjectHeaderProps {
  name: string;
  totals: ProjectHeaderTotals;
}

function statusBadge(variance: number): { label: string; className: string } {
  if (variance <= 0) {
    return {
      label: "В норме",
      className: "bg-success/10 text-success border-success/30",
    };
  }
  if (variance <= 15) {
    return {
      label: "Внимание",
      className: "bg-warning/10 text-warning border-warning/30",
    };
  }
  return {
    label: "Перерасход",
    className: "bg-warning text-white border-warning",
  };
}

export function ProjectHeader({ name, totals }: ProjectHeaderProps) {
  const badge = statusBadge(totals.variance_pct);
  return (
    <header
      className="bg-surface border border-border rounded-card p-5 shadow-card flex flex-col gap-3"
      data-testid="project-header"
    >
      <div className="flex items-center gap-3 min-w-0">
        <Link
          to="/"
          className="text-sm text-muted hover:text-ink min-h-11 flex items-center flex-shrink-0"
          data-testid="back-link"
        >
          ←&nbsp;<span className="hidden sm:inline">Дашборд</span>
        </Link>
        <h1 className="font-heading text-lg md:text-2xl text-ink flex-1 truncate min-w-0">
          {name}
        </h1>
        <span
          className={`inline-block text-xs px-3 py-1 rounded-pill border flex-shrink-0 ${badge.className}`}
        >
          {badge.label}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <div>
          <span className="text-muted">Бюджет план:&nbsp;</span>
          <span className="text-ink tabular font-medium">
            {formatMoney(totals.total_plan, { compact: true })}
          </span>
        </div>
        <div>
          <span className="text-muted">Факт:&nbsp;</span>
          <span className="text-ink tabular font-medium">
            {formatMoney(totals.total_actual, { compact: true })}
          </span>
        </div>
        <div>
          <span className="text-muted">Отклонение:&nbsp;</span>
          <span
            className={`tabular font-medium ${totals.variance_pct > 15 ? "text-warning" : "text-ink"}`}
          >
            {totals.variance_pct > 0 ? "+" : ""}
            {formatPercent(totals.variance_pct, 1)}
          </span>
        </div>
        <div>
          <span className="text-muted">Выполнено:&nbsp;</span>
          <span className="text-ink tabular font-medium">
            {formatPercent(totals.completion_pct, 0)}
          </span>
        </div>
      </div>
    </header>
  );
}
