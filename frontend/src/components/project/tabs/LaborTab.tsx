import { useMemo, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import type { BudgetTimeline, LaborRow } from "../../../lib/api";
import { formatMoney, formatPercent, formatHours, variancePct, varianceTier, TIER_ROW_BG, TIER_ICON } from "../../../lib/format";
import { BudgetTimelineChart } from "../../BudgetTimelineChart";

interface LaborTabProps {
  rows: LaborRow[];
  timeline?: BudgetTimeline;
}

function LaborChart({ rows }: { rows: LaborRow[] }) {
  const data = rows.map((r) => ({
    name: r.specialty.length > 20 ? r.specialty.slice(0, 18) + "…" : r.specialty,
    plan: parseFloat(r.hours_plan.toFixed(1)),
    fact: parseFloat(r.hours_actual.toFixed(1)),
  }));

  return (
    <div className="bg-surface border border-border rounded-card p-4 shadow-card">
      <ResponsiveContainer width="100%" height={Math.max(220, data.length * 36)}>
        <BarChart data={data} layout="vertical" margin={{ left: 16, right: 24, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e5e7eb" />
          <XAxis
            type="number"
            tick={{ fontSize: 11, fill: "#78716c" }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 11, fill: "#44403c" }}
            tickLine={false}
            axisLine={false}
            width={130}
          />
          <Tooltip />
          <Legend />
          <Bar dataKey="plan" name="План, ч" fill="#94a3b8" radius={[0, 3, 3, 0]} />
          <Bar dataKey="fact" name="Факт, ч" fill="#3ba6f1" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LaborTab({ rows, timeline }: LaborTabProps) {
  const [view, setView] = useState<"table" | "chart" | "timeline">("table");
  const [selectedItem, setSelectedItem] = useState<string>("__all__");

  const itemNames = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => set.add(r.specialty));
    return Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
  }, [rows]);

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
    <div className="flex flex-col gap-3" data-testid="labor-tab">
      <div className="flex justify-end">
        <div className="flex gap-1 p-0.5 bg-bg border border-border rounded-pill text-xs">
          {(["table", "chart", "timeline"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className={`px-3 py-1 min-h-11 rounded-pill transition-colors ${
                view === v
                  ? "bg-surface text-ink font-medium shadow-card"
                  : "text-muted hover:text-ink"
              }`}
            >
              {v === "table" ? "Таблица" : v === "chart" ? "График" : "Динамика"}
            </button>
          ))}
        </div>
      </div>

      {view === "timeline" ? (
        <div className="bg-surface border border-border rounded-card p-4 shadow-card">
          <div className="flex items-center gap-3 mb-3">
            <label className="text-xs text-muted">Показать:</label>
            <select
              value={selectedItem}
              onChange={(e) => setSelectedItem(e.target.value)}
              className="text-sm border border-border bg-bg rounded-card px-2 py-1 text-ink focus:outline-none focus:border-accent"
            >
              <option value="__all__">Все трудозатраты</option>
              {itemNames.map((n) => (
                <option key={n} value={n} disabled title="Историчность по конкретной позиции появится после расширения снапшотов">
                  {n} (нет историчности)
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-4 text-xs text-muted mb-3 flex-wrap">
            <span className="flex items-center gap-1.5">
              <span style={{ display: "inline-block", width: 24, borderTop: "2px dashed #94a3b8" }} />
              План
            </span>
            <span className="flex items-center gap-1.5">
              <span style={{ display: "inline-block", width: 24, borderTop: "2px solid #3ba6f1" }} />
              Факт
            </span>
          </div>
          {timeline ? (
            <BudgetTimelineChart timeline={timeline} category="labor" height={260} />
          ) : (
            <div className="text-muted text-sm">Нет данных динамики</div>
          )}
        </div>
      ) : view === "chart" ? (
        <LaborChart rows={rows} />
      ) : (
        <div className="bg-surface border border-border rounded-card overflow-hidden shadow-card">
          <table className="w-full text-sm">
            <thead className="bg-bg border-b border-border text-muted text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Специальность</th>
                <th className="px-4 py-3 text-left font-medium">Этап / Задача</th>
                <th className="px-4 py-3 text-right font-medium">Ставка</th>
                <th className="px-4 py-3 text-right font-medium">Часов план</th>
                <th className="px-4 py-3 text-right font-medium">Часов факт</th>
                <th className="px-4 py-3 text-right font-medium">ФОТ план/факт</th>
                <th className="px-4 py-3 text-right font-medium">Откл.</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const v = variancePct(r.payroll_plan, r.payroll_actual);
                const tier = varianceTier(v);
                const icon = TIER_ICON[tier];
                return (
                  <tr
                    key={r.id}
                    data-testid={`labor-row-${r.id}`}
                    className={`border-b border-border last:border-0 ${TIER_ROW_BG[tier]}`}
                  >
                    <td className="px-4 py-3 text-ink font-medium">{r.specialty}</td>
                    <td className="px-4 py-3 text-muted">
                      <div>{r.phase}</div>
                      <div className="text-xs">{r.task_name}</div>
                    </td>
                    <td className="px-4 py-3 text-right tabular text-ink">
                      {formatMoney(r.rate)}/ч
                    </td>
                    <td className="px-4 py-3 text-right tabular text-muted">
                      {formatHours(r.hours_plan)}
                    </td>
                    <td className="px-4 py-3 text-right tabular text-ink">
                      {formatHours(r.hours_actual)}
                    </td>
                    <td className="px-4 py-3 text-right tabular">
                      <div className="text-muted">
                        {formatMoney(r.payroll_plan, { compact: true })}
                      </div>
                      <div className="text-ink font-medium">
                        {formatMoney(r.payroll_actual, { compact: true })}
                      </div>
                    </td>
                    <td
                      className={`px-4 py-3 text-right tabular font-medium ${
                        tier === "high" ? "text-warning" : "text-ink"
                      }`}
                    >
                      {icon && <span className="mr-1">{icon}</span>}
                      {v > 0 ? "+" : ""}
                      {formatPercent(v, 1)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
