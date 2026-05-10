import type { MaterialRow } from "../../../lib/api";
import { formatMoney, formatPercent } from "../../../lib/format";

interface MaterialDetailPanelProps {
  material: MaterialRow;
}

export function MaterialDetailPanel({ material }: MaterialDetailPanelProps) {
  const consumedPct = material.qty_plan
    ? (material.qty_consumed / material.qty_plan) * 100
    : 0;
  const priceDeltaPct = material.price_plan
    ? ((material.price_actual - material.price_plan) / material.price_plan) * 100
    : 0;
  const overpriced = priceDeltaPct > 5;

  return (
    <div className="flex flex-col gap-5" data-testid="material-detail-panel">
      <div>
        <div className="text-xs text-muted uppercase tracking-wide mb-1">
          {material.phase} · {material.task_name}
        </div>
        <h3 className="text-lg font-heading text-ink">{material.material_name}</h3>
        <div className="text-sm text-muted mt-1">{material.unit}</div>
      </div>

      <div className="bg-bg border border-border rounded-card p-4">
        <div className="flex items-center justify-between mb-2 text-sm">
          <span className="text-muted">Расход</span>
          <span className="text-ink tabular font-medium">
            {material.qty_consumed} / {material.qty_plan} {material.unit}
          </span>
        </div>
        <div
          className="w-full h-2 bg-border rounded-pill overflow-hidden"
          role="progressbar"
          aria-valuenow={Math.round(consumedPct)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full bg-accent transition-all"
            style={{ width: `${Math.min(100, consumedPct)}%` }}
          />
        </div>
        <div className="text-xs text-muted mt-1">{formatPercent(consumedPct, 0)} от плана</div>
      </div>

      <div className="bg-bg border border-border rounded-card p-4 grid grid-cols-2 gap-y-2 text-sm">
        <div className="text-muted">Куплено</div>
        <div className="text-right tabular text-ink">{material.qty_bought} {material.unit}</div>
        <div className="text-muted">На складе</div>
        <div className="text-right tabular text-ink">{material.qty_stock} {material.unit}</div>
      </div>

      <div className={`border rounded-card p-4 grid grid-cols-2 gap-y-2 text-sm ${
        overpriced ? "border-warning bg-warning/5" : "border-border bg-bg"
      }`}>
        <div className="text-muted">Цена план</div>
        <div className="text-right tabular text-ink">{formatMoney(material.price_plan)}</div>
        <div className="text-muted">Цена факт</div>
        <div className="text-right tabular text-ink">{formatMoney(material.price_actual)}</div>
        <div className="text-muted">Δ цены</div>
        <div className={`text-right tabular font-medium ${overpriced ? "text-warning" : "text-ink"}`}>
          {priceDeltaPct > 0 ? "+" : ""}
          {formatPercent(priceDeltaPct, 1)}
        </div>
      </div>

      <div className="border-t border-border pt-3 text-sm grid grid-cols-2 gap-y-2">
        <div className="text-muted">Стоимость план</div>
        <div className="text-right tabular text-ink">{formatMoney(material.cost_plan, { compact: true })}</div>
        <div className="text-muted">Стоимость факт</div>
        <div className="text-right tabular text-ink font-medium">
          {formatMoney(material.cost_actual, { compact: true })}
        </div>
      </div>
    </div>
  );
}
