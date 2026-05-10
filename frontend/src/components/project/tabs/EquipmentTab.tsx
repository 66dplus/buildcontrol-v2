import type { EquipmentRow } from "../../../lib/api";
import { formatMoney, formatPercent, variancePct } from "../../../lib/format";

interface EquipmentTabProps {
  rows: EquipmentRow[];
}

export function EquipmentTab({ rows }: EquipmentTabProps) {
  if (rows.length === 0) {
    return (
      <div
        className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center"
        data-testid="equipment-empty"
      >
        Нет данных по технике
      </div>
    );
  }

  return (
    <div
      className="bg-surface border border-border rounded-card overflow-hidden shadow-card"
      data-testid="equipment-tab"
    >
      <table className="w-full text-sm">
        <thead className="bg-bg border-b border-border text-muted text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Техника</th>
            <th className="px-4 py-3 text-left font-medium">Этап / Задача</th>
            <th className="px-4 py-3 text-right font-medium">Цена</th>
            <th className="px-4 py-3 text-right font-medium">Часов план/факт</th>
            <th className="px-4 py-3 text-right font-medium">Итого план/факт</th>
            <th className="px-4 py-3 text-right font-medium">Откл.</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const v = variancePct(r.total_plan, r.total_actual);
            const overrun = v > 15;
            return (
              <tr
                key={r.id}
                data-testid={`equipment-row-${r.id}`}
                className={`border-b border-border last:border-0 ${
                  overrun ? "bg-warning/5" : ""
                }`}
              >
                <td className="px-4 py-3 text-ink font-medium">{r.equipment_name}</td>
                <td className="px-4 py-3 text-muted">
                  <div>{r.phase}</div>
                  <div className="text-xs">{r.task_name}</div>
                </td>
                <td className="px-4 py-3 text-right tabular text-ink">
                  {formatMoney(r.price_per_hour)}/ч
                </td>
                <td className="px-4 py-3 text-right tabular">
                  <div className="text-muted">{r.hours_plan}</div>
                  <div className="text-ink">{r.hours_actual}</div>
                </td>
                <td className="px-4 py-3 text-right tabular">
                  <div className="text-muted">{formatMoney(r.total_plan, { compact: true })}</div>
                  <div className="text-ink font-medium">
                    {formatMoney(r.total_actual, { compact: true })}
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
