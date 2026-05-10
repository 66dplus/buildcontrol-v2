import type { BudgetPhase } from "../../../lib/api";
import { formatMoney, formatPercent, variancePct } from "../../../lib/format";
import { PhaseChart } from "../PhaseChart";

interface OverviewTabProps {
  phases: BudgetPhase[];
}

export function OverviewTab({ phases }: OverviewTabProps) {
  return (
    <div className="flex flex-col gap-6" data-testid="overview-tab">
      <PhaseChart phases={phases} />
      <PhaseBreakdownTable phases={phases} />
    </div>
  );
}

function PhaseBreakdownTable({ phases }: { phases: BudgetPhase[] }) {
  if (phases.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-card p-6 text-muted text-sm text-center">
        Нет данных по этапам
      </div>
    );
  }

  return (
    <div
      className="bg-surface border border-border rounded-card overflow-hidden shadow-card"
      data-testid="phase-breakdown"
    >
      <table className="w-full text-sm">
        <thead className="bg-bg border-b border-border text-muted text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Этап</th>
            <th className="px-4 py-3 text-right font-medium">Материалы план/факт</th>
            <th className="px-4 py-3 text-right font-medium">Труд план/факт</th>
            <th className="px-4 py-3 text-right font-medium">Техника план/факт</th>
            <th className="px-4 py-3 text-right font-medium">Итого план/факт</th>
            <th className="px-4 py-3 text-right font-medium">Откл.</th>
          </tr>
        </thead>
        <tbody>
          {phases.map((p) => {
            const v = variancePct(p.total_plan, p.total_actual);
            const overrun = v > 15;
            return (
              <tr
                key={p.id}
                data-testid={`phase-row-${p.id}`}
                className={`border-b border-border last:border-0 ${
                  overrun ? "bg-warning/5" : ""
                }`}
              >
                <td className="px-4 py-3 text-ink font-medium">{p.phase_name}</td>
                <td className="px-4 py-3 text-right tabular text-muted">
                  <div>{formatMoney(p.materials_plan, { compact: true })}</div>
                  <div className="text-ink">{formatMoney(p.materials_actual, { compact: true })}</div>
                </td>
                <td className="px-4 py-3 text-right tabular text-muted">
                  <div>{formatMoney(p.labor_plan, { compact: true })}</div>
                  <div className="text-ink">{formatMoney(p.labor_actual, { compact: true })}</div>
                </td>
                <td className="px-4 py-3 text-right tabular text-muted">
                  <div>{formatMoney(p.equipment_plan, { compact: true })}</div>
                  <div className="text-ink">{formatMoney(p.equipment_actual, { compact: true })}</div>
                </td>
                <td className="px-4 py-3 text-right tabular">
                  <div className="text-muted">{formatMoney(p.total_plan, { compact: true })}</div>
                  <div className="text-ink font-medium">
                    {formatMoney(p.total_actual, { compact: true })}
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
