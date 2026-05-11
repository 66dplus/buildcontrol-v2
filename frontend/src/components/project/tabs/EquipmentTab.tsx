import { useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import type { EquipmentRow } from "../../../lib/api";
import { formatMoney, formatPercent, formatHours, variancePct, varianceTier, TIER_ROW_BG, TIER_ICON } from "../../../lib/format";

interface EquipmentTabProps {
  rows: EquipmentRow[];
}

function EquipmentChart({ rows }: { rows: EquipmentRow[] }) {
  const data = rows.map((r) => ({
    name:
      r.equipment_name.length > 20
        ? r.equipment_name.slice(0, 18) + "…"
        : r.equipment_name,
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

export function EquipmentTab({ rows }: EquipmentTabProps) {
  const [view, setView] = useState<"table" | "chart">("table");

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
    <div className="flex flex-col gap-3" data-testid="equipment-tab">
      <div className="flex justify-end">
        <div className="flex gap-1 p-0.5 bg-bg border border-border rounded-pill text-xs">
          {(["table", "chart"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className={`px-3 py-1 rounded-pill transition-colors ${
                view === v
                  ? "bg-surface text-ink font-medium shadow-card"
                  : "text-muted hover:text-ink"
              }`}
            >
              {v === "table" ? "Таблица" : "График"}
            </button>
          ))}
        </div>
      </div>

      {view === "chart" ? (
        <EquipmentChart rows={rows} />
      ) : (
        <div className="bg-surface border border-border rounded-card overflow-hidden shadow-card">
          <table className="w-full text-sm">
            <thead className="bg-bg border-b border-border text-muted text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Техника</th>
                <th className="px-4 py-3 text-left font-medium">Этап / Задача</th>
                <th className="px-4 py-3 text-right font-medium">Цена</th>
                <th className="px-4 py-3 text-right font-medium">Часов план</th>
                <th className="px-4 py-3 text-right font-medium">Часов факт</th>
                <th className="px-4 py-3 text-right font-medium">Итого план/факт</th>
                <th className="px-4 py-3 text-right font-medium">Откл.</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const v = variancePct(r.total_plan, r.total_actual);
                const tier = varianceTier(v);
                const icon = TIER_ICON[tier];
                return (
                  <tr
                    key={r.id}
                    data-testid={`equipment-row-${r.id}`}
                    className={`border-b border-border last:border-0 ${TIER_ROW_BG[tier]}`}
                  >
                    <td className="px-4 py-3 text-ink font-medium">{r.equipment_name}</td>
                    <td className="px-4 py-3 text-muted">
                      <div>{r.phase}</div>
                      <div className="text-xs">{r.task_name}</div>
                    </td>
                    <td className="px-4 py-3 text-right tabular text-ink">
                      {formatMoney(r.price_per_hour)}/ч
                    </td>
                    <td className="px-4 py-3 text-right tabular text-muted">
                      {formatHours(r.hours_plan)}
                    </td>
                    <td className="px-4 py-3 text-right tabular text-ink">
                      {formatHours(r.hours_actual)}
                    </td>
                    <td className="px-4 py-3 text-right tabular">
                      <div className="text-muted">
                        {formatMoney(r.total_plan, { compact: true })}
                      </div>
                      <div className="text-ink font-medium">
                        {formatMoney(r.total_actual, { compact: true })}
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
