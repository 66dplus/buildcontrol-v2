import type { MaterialRow } from "../../../lib/api";
import { formatMoney } from "../../../lib/format";
import { useSidePanel } from "../../../contexts/SidePanelContext";
import { MaterialDetailPanel } from "../panels/MaterialDetailPanel";

interface MaterialsTabProps {
  materials: MaterialRow[];
}

export function MaterialsTab({ materials }: MaterialsTabProps) {
  const { openPanel } = useSidePanel();

  if (materials.length === 0) {
    return (
      <div
        className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center"
        data-testid="materials-empty"
      >
        Нет материалов в этом проекте
      </div>
    );
  }

  return (
    <div
      className="bg-surface border border-border rounded-card overflow-hidden shadow-card"
      data-testid="materials-tab"
    >
      <table className="w-full text-sm">
        <thead className="bg-bg border-b border-border text-muted text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Материал</th>
            <th className="px-4 py-3 text-left font-medium">Этап / Задача</th>
            <th className="px-4 py-3 text-right font-medium">План</th>
            <th className="px-4 py-3 text-right font-medium">Куплено</th>
            <th className="px-4 py-3 text-right font-medium">Расход</th>
            <th className="px-4 py-3 text-right font-medium">Склад</th>
            <th className="px-4 py-3 text-right font-medium">Цена план→факт</th>
            <th className="px-4 py-3 text-right font-medium">Стоимость факт</th>
          </tr>
        </thead>
        <tbody>
          {materials.map((m) => {
            const overpriced =
              m.price_plan > 0 && m.price_actual > m.price_plan * 1.05;
            return (
              <tr
                key={m.id}
                onClick={() => openPanel(<MaterialDetailPanel material={m} />)}
                data-testid={`material-row-${m.id}`}
                className={`border-b border-border last:border-0 hover:bg-bg cursor-pointer transition-colors ${
                  overpriced ? "bg-warning/5" : ""
                }`}
              >
                <td className="px-4 py-3 text-ink font-medium">{m.material_name}</td>
                <td className="px-4 py-3 text-muted">
                  <div>{m.phase}</div>
                  <div className="text-xs">{m.task_name}</div>
                </td>
                <td className="px-4 py-3 text-right tabular text-ink">
                  {m.qty_plan} {m.unit}
                </td>
                <td className="px-4 py-3 text-right tabular text-ink">{m.qty_bought}</td>
                <td className="px-4 py-3 text-right tabular text-ink">{m.qty_consumed}</td>
                <td className="px-4 py-3 text-right tabular text-ink">{m.qty_stock}</td>
                <td className={`px-4 py-3 text-right tabular ${overpriced ? "text-warning font-medium" : "text-ink"}`}>
                  {formatMoney(m.price_plan)} → {formatMoney(m.price_actual)}
                </td>
                <td className="px-4 py-3 text-right tabular text-ink font-medium">
                  {formatMoney(m.cost_actual, { compact: true })}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
