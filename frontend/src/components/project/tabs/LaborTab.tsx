import type { LaborRow } from "../../../lib/api";
import { formatMoney, formatPercent, variancePct } from "../../../lib/format";

interface LaborTabProps {
  rows: LaborRow[];
}

export function LaborTab({ rows }: LaborTabProps) {
  if (rows.length === 0) {
    return (
      <div
        className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center"
        data-testid="labor-empty"
      >
        Нет данных по трудозатратам
      </div>
    );
  }

  return (
    <div
      className="bg-surface border border-border rounded-card overflow-hidden shadow-card"
      data-testid="labor-tab"
    >
      <table className="w-full text-sm">
        <thead className="bg-bg border-b border-border text-muted text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Специальность</th>
            <th className="px-4 py-3 text-left font-medium">Этап / Задача</th>
            <th className="px-4 py-3 text-right font-medium">Ставка</th>
            <th className="px-4 py-3 text-right font-medium">Часов план/факт</th>
            <th className="px-4 py-3 text-right font-medium">ФОТ план/факт</th>
            <th className="px-4 py-3 text-right font-medium">Откл.</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const v = variancePct(r.payroll_plan, r.payroll_actual);
            const overrun = v > 15;
            return (
              <tr
                key={r.id}
                data-testid={`labor-row-${r.id}`}
                className={`border-b border-border last:border-0 ${
                  overrun ? "bg-warning/5" : ""
                }`}
              >
                <td className="px-4 py-3 text-ink font-medium">{r.specialty}</td>
                <td className="px-4 py-3 text-muted">
                  <div>{r.phase}</div>
                  <div className="text-xs">{r.task_name}</div>
                </td>
                <td className="px-4 py-3 text-right tabular text-ink">
                  {formatMoney(r.rate)}/ч
                </td>
                <td className="px-4 py-3 text-right tabular">
                  <div className="text-muted">{r.hours_plan}</div>
                  <div className="text-ink">{r.hours_actual}</div>
                </td>
                <td className="px-4 py-3 text-right tabular">
                  <div className="text-muted">{formatMoney(r.payroll_plan, { compact: true })}</div>
                  <div className="text-ink font-medium">
                    {formatMoney(r.payroll_actual, { compact: true })}
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
