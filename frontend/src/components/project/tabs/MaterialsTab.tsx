import { useMemo, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import { api, type BudgetTimeline, type MaterialRow, type TaskRow } from "../../../lib/api";
import { formatQty, varianceTier, TIER_ROW_BG, TIER_ICON } from "../../../lib/format";
import { useSidePanel } from "../../../contexts/SidePanelContext";
import { MaterialDetailPanel } from "../panels/MaterialDetailPanel";
import { BudgetTimelineChart } from "../../BudgetTimelineChart";
import { AddItemModal } from "../../AddItemModal";

interface MaterialsTabProps {
  materials: MaterialRow[];
  timeline?: BudgetTimeline;
  projectId: number;
  tasks: TaskRow[];
  onAdded: () => void;
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

export function MaterialsTab({ materials, timeline, projectId, tasks, onAdded }: MaterialsTabProps) {
  const { openPanel } = useSidePanel();
  const [view, setView] = useState<"table" | "chart" | "timeline">("table");
  const [selectedItem, setSelectedItem] = useState<string>("__all__");
  const [showAdd, setShowAdd] = useState(false);

  const itemNames = useMemo(() => {
    const set = new Set<string>();
    materials.forEach((m) => set.add(m.material_name));
    return Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
  }, [materials]);

  const phaseOptions = useMemo(() => {
    const set = new Set<string>();
    tasks.forEach((t) => set.add(t.phase));
    materials.forEach((m) => set.add(m.phase));
    return Array.from(set).filter(Boolean).sort((a, b) => a.localeCompare(b, "ru"));
  }, [tasks, materials]);

  const taskOptions = useMemo(
    () => tasks.map((t) => ({ phase: t.phase, task_name: t.task_name })),
    [tasks],
  );

  const addButton = (
    <button
      type="button"
      onClick={() => setShowAdd(true)}
      className="bg-accent text-white text-xs font-medium rounded-pill px-3 py-1.5 hover:bg-accent/90 min-h-[36px]"
      data-testid="add-material-btn"
    >
      + Добавить
    </button>
  );

  const modal = showAdd && (
    <AddItemModal
      kind="material"
      phaseOptions={phaseOptions}
      taskOptions={taskOptions}
      onClose={() => setShowAdd(false)}
      onSubmit={async (payload) => {
        await api.addMaterial(projectId, payload as Parameters<typeof api.addMaterial>[1]);
        onAdded();
      }}
    />
  );

  if (materials.length === 0) {
    return (
      <div className="flex flex-col gap-3" data-testid="materials-tab">
        <div className="flex justify-end">{addButton}</div>
        <div
          className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center"
          data-testid="materials-empty"
        >
          Нет материалов в этом проекте
        </div>
        {modal}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="materials-tab">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {addButton}
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
        (() => {
          const sumPlan = materials.reduce((s, r) => s + r.cost_plan, 0);
          const sumActual = materials.reduce((s, r) => s + r.cost_actual, 0);
          const selected = selectedItem === "__all__"
            ? null
            : materials.find((r) => r.material_name === selectedItem);
          const planScale = selected && sumPlan > 0 ? selected.cost_plan / sumPlan : 1;
          const actualScale = selected && sumActual > 0 ? selected.cost_actual / sumActual : 1;
          return (
            <div className="bg-surface border border-border rounded-card p-4 shadow-card">
              <div className="flex items-center gap-3 mb-3">
                <label className="text-xs text-muted">Показать:</label>
                <select
                  value={selectedItem}
                  onChange={(e) => setSelectedItem(e.target.value)}
                  className="text-sm border border-border bg-bg rounded-card px-2 py-1 text-ink focus:outline-none focus:border-accent"
                >
                  <option value="__all__">Все материалы</option>
                  {itemNames.map((n) => (
                    <option key={n} value={n}>{n}</option>
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
                {selected && (
                  <span className="text-muted/70">
                    Доля позиции в категории — пропорциональная оценка кривой
                  </span>
                )}
              </div>
              {timeline ? (
                <BudgetTimelineChart
                  timeline={timeline}
                  category="materials"
                  height={260}
                  planScale={planScale}
                  actualScale={actualScale}
                />
              ) : (
                <div className="text-muted text-sm">Нет данных динамики</div>
              )}
            </div>
          );
        })()
      ) : view === "chart" ? (
        <MaterialsChart materials={materials} />
      ) : (
        <div className="bg-surface border border-border rounded-card overflow-x-auto shadow-card">
          <table className="w-full text-sm min-w-[820px]">
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
                const devPct =
                  m.qty_plan > 0
                    ? ((m.qty_consumed - m.qty_plan) / m.qty_plan) * 100
                    : 0;
                const tier = varianceTier(devPct);
                const icon = TIER_ICON[tier];
                return (
                  <tr
                    key={m.id}
                    onClick={() => openPanel(<MaterialDetailPanel material={m} />)}
                    data-testid={`material-row-${m.id}`}
                    className={`border-b border-border last:border-0 hover:bg-bg cursor-pointer transition-colors ${TIER_ROW_BG[tier]}`}
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
                        tier === "high" ? "text-warning" : "text-ink"
                      }`}
                    >
                      {icon && <span className="mr-1">{icon}</span>}
                      {devPct > 0 ? "+" : ""}{devPct.toFixed(1)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {modal}
    </div>
  );
}
