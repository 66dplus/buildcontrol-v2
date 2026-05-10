import { useState } from "react";
import type { BudgetPhase, BudgetTimeline } from "../../../lib/api";
import { formatMoney, formatPercent, variancePct } from "../../../lib/format";
import { BudgetTimelineChart, type Category } from "../../BudgetTimelineChart";

interface OverviewTabProps {
  phases: BudgetPhase[];
  timeline: BudgetTimeline;
}

const CATEGORIES: Array<{ key: Category; label: string }> = [
  { key: "total",     label: "Итого" },
  { key: "materials", label: "Материалы" },
  { key: "labor",     label: "Труд" },
  { key: "equipment", label: "Техника" },
];

function BudgetBar({ plan, actual, label }: { plan: number; actual: number; label: string }) {
  const pct = plan > 0 ? Math.min((actual / plan) * 100, 150) : 0;
  const overrun = actual > plan;
  return (
    <div className="mb-1">
      <div className="flex justify-between text-xs text-muted mb-1">
        <span>{label}</span>
        <span className={overrun ? "text-warning font-medium" : "text-ink"}>
          {formatMoney(actual, { compact: true })} / {formatMoney(plan, { compact: true })}
          {overrun ? " ⚠" : ""}
        </span>
      </div>
      <div className="h-2 bg-bg rounded-full overflow-hidden border border-border">
        <div
          className={`h-full rounded-full ${overrun ? "bg-warning" : "bg-accent"}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  );
}

export function OverviewTab({ phases, timeline }: OverviewTabProps) {
  const [category, setCategory] = useState<Category>("total");

  if (phases.length === 0) {
    return (
      <div
        className="bg-surface border border-border rounded-card p-6 text-muted text-sm text-center"
        data-testid="overview-tab"
      >
        Нет данных по этапам
      </div>
    );
  }

  const totalPlan   = phases.reduce((s, p) => s + p.total_plan, 0);
  const totalActual = phases.reduce((s, p) => s + p.total_actual, 0);
  const matPlan     = phases.reduce((s, p) => s + p.materials_plan, 0);
  const matActual   = phases.reduce((s, p) => s + p.materials_actual, 0);
  const labPlan     = phases.reduce((s, p) => s + p.labor_plan, 0);
  const labActual   = phases.reduce((s, p) => s + p.labor_actual, 0);
  const eqPlan      = phases.reduce((s, p) => s + p.equipment_plan, 0);
  const eqActual    = phases.reduce((s, p) => s + p.equipment_actual, 0);
  const v = variancePct(totalPlan, totalActual);

  return (
    <div className="flex flex-col gap-5" data-testid="overview-tab">
      {/* Overall project totals */}
      <div className="bg-surface border border-border rounded-card p-5 shadow-card">
        <div className="flex items-start justify-between mb-4">
          <div>
            <p className="text-xs text-muted uppercase tracking-wide font-medium">Итого по проекту</p>
            <div className="flex items-baseline gap-3 mt-1">
              <span className="text-2xl font-heading text-ink">
                {formatMoney(totalActual, { compact: true })}
              </span>
              <span className="text-muted text-sm">из {formatMoney(totalPlan, { compact: true })}</span>
            </div>
          </div>
          <span
            className={`text-sm font-medium px-3 py-1 rounded-pill ${
              v > 15
                ? "bg-warning/10 text-warning"
                : v > 0
                ? "bg-bg text-muted border border-border"
                : "bg-accent/10 text-accent"
            }`}
          >
            {v > 0 ? "+" : ""}{formatPercent(v, 1)}
          </span>
        </div>
        <div className="space-y-2">
          <BudgetBar plan={totalPlan} actual={totalActual} label="Итого" />
          <BudgetBar plan={matPlan}   actual={matActual}   label="Материалы" />
          <BudgetBar plan={labPlan}   actual={labActual}   label="Труд" />
          <BudgetBar plan={eqPlan}    actual={eqActual}    label="Техника" />
        </div>
      </div>

      {/* Timeline chart with category switcher */}
      <div className="bg-surface border border-border rounded-card p-5 shadow-card">
        <div className="flex items-center justify-between mb-4">
          <p className="text-xs text-muted uppercase tracking-wide font-medium">Динамика по времени</p>
          <div className="flex gap-1 p-0.5 bg-bg border border-border rounded-pill text-xs">
            {CATEGORIES.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => setCategory(key)}
                data-testid={`category-tab-${key}`}
                className={`px-3 py-1 rounded-pill transition-colors ${
                  category === key
                    ? "bg-surface text-ink font-medium shadow-card"
                    : "text-muted hover:text-ink"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted mb-3">
          {category === "total" && (
            <span className="flex items-center gap-1.5">
              <span style={{ display: "inline-block", width: 24, borderTop: "2px dashed #94a3b8" }} />
              План
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <span style={{ display: "inline-block", width: 24, borderTop: "2px solid #3ba6f1" }} />
            Факт
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-warning" />
            Перерасход &gt;10%
          </span>
        </div>
        <BudgetTimelineChart timeline={timeline} category={category} height={220} />
      </div>
    </div>
  );
}
