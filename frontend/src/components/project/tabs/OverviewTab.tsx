import { useState } from "react";
import type { BudgetPhase, BudgetTimeline } from "../../../lib/api";
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

  return (
    <div className="flex flex-col gap-5" data-testid="overview-tab">
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
          <span className="flex items-center gap-1.5">
            <span style={{ display: "inline-block", width: 24, borderTop: "2px dashed #94a3b8" }} />
            План
          </span>
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
