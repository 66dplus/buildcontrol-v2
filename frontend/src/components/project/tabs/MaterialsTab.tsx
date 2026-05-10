import { useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import type { MaterialRow } from "../../../lib/api";
import { formatQty } from "../../../lib/format";
import { useSidePanel } from "../../../contexts/SidePanelContext";
import { MaterialDetailPanel } from "../panels/MaterialDetailPanel";

interface MaterialsTabProps {
  materials: MaterialRow[];
}

function fmtCompact(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(Math.round(n));
}

function MaterialsChart({ materials }: { materials: MaterialRow[] }) {
  const data = materials.map((m) => ({
    name: m.material_name.length > 20 ? m.material_name.slice(0, 18) + "…" : m.material_name,
    plan: parseFloat(m.qty_plan.toFixed(2)),
    used: parseFloat(m.qty_consumed.toFixed(2)),
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
            tickFormatter={fmtCompact}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 11, fill: "#44403c" }}
            tickLine={false}
            axisLine={false}
            width={130}
          />
          <Tooltip formatter={(v: number) => v.toFixed(2)} />
          <Legend />
          <Bar dataKey="plan" name="План" fill="#94a3b8" radius={[0, 3, 3, 0]} />
          <Bar dataKey="used" name="Расход" fill="#3ba6f1" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MaterialsTab({ materials }: MaterialsTabProps) {
  const { openPanel } = useSidePanel();
  const [view, setView] = useState<"table" | "chart">("table");

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
    <div className="flex flex-col gap-3" data-testid="materials-tab">
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
        <MaterialsChart materials={materials} />
      ) : (
        <div className="bg-surface border border-border rounded-card overflow-hidden shadow-card">
          <table className="w-full text-sm">
            <thead className="bg-bg border-b border-border text-muted text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Материал</th>
                <th className="px-4 py-3 text-left font-medium">Этап / Задача</th>
                <th className="px-4 py-3 text-right font-medium">Ед.</th>
                <th className="px-4 py-3 text-right font-medium">План</th>
                <th className="px-4 py-3 text-right font-medium">Куплено</th>
                <th className="px-4 py-3 text-right font-medium">Расход</th>
                <th className="px-4 py-3 text-right font-medium">Склад</th>
                <th className="px-4 py-3 text-right font-medium">Откл.</th>
              </tr>
            </thead>
            <tbody>
              {materials.map((m) => {
                const overused = m.qty_plan > 0 && m.qty_consumed > m.qty_plan * 1.05;
                const devPct =
                  m.qty_plan > 0
                    ? ((m.qty_consumed - m.qty_plan) / m.qty_plan) * 100
                    : 0;
                return (
                  <tr
                    key={m.id}
                    onClick={() => openPanel(<MaterialDetailPanel material={m} />)}
                    data-testid={`material-row-${m.id}`}
                    className={`border-b border-border last:border-0 hover:bg-bg cursor-pointer transition-colors ${
                      overused ? "bg-warning/5" : ""
                    }`}
                  >
                    <td className="px-4 py-3 text-ink font-medium">{m.material_name}</td>
                    <td className="px-4 py-3 text-muted">
                      <div>{m.phase}</div>
                      <div className="text-xs">{m.task_name}</div>
                    </td>
                    <td className="px-4 py-3 text-right tabular text-muted">{m.unit}</td>
                    <td className="px-4 py-3 text-right tabular text-ink">{formatQty(m.qty_plan)}</td>
                    <td className="px-4 py-3 text-right tabular text-ink">{formatQty(m.qty_bought)}</td>
                    <td className="px-4 py-3 text-right tabular text-ink">{formatQty(m.qty_consumed)}</td>
                    <td className="px-4 py-3 text-right tabular text-ink">{formatQty(m.qty_stock)}</td>
                    <td
                      className={`px-4 py-3 text-right tabular font-medium ${
                        overused ? "text-warning" : "text-ink"
                      }`}
                    >
                      {devPct > 0 ? "+" : ""}{devPct.toFixed(1)}%
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
