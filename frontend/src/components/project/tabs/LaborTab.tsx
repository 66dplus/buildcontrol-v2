import { useMemo, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import { api, type BudgetTimeline, type LaborRow, type TaskRow } from "../../../lib/api";
import { formatMoney, formatPercent, formatHours, variancePct, varianceTier, TIER_ROW_BG, TIER_ICON } from "../../../lib/format";
import { BudgetTimelineChart } from "../../BudgetTimelineChart";
import { AddItemModal } from "../../AddItemModal";

interface LaborTabProps {
  rows: LaborRow[];
  timeline?: BudgetTimeline;
  projectId: number;
  tasks: TaskRow[];
  onAdded: () => void;
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

export function LaborTab({ rows, timeline, projectId, tasks, onAdded }: LaborTabProps) {
  const [view, setView] = useState<"table" | "chart" | "timeline">("table");
  const [selectedItem, setSelectedItem] = useState<string>("__all__");
  const [showAdd, setShowAdd] = useState(false);

  const itemNames = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => set.add(r.specialty));
    return Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
  }, [rows]);

  const phaseOptions = useMemo(() => {
    const set = new Set<string>();
    tasks.forEach((t) => set.add(t.phase));
    rows.forEach((r) => set.add(r.phase));
    return Array.from(set).filter(Boolean).sort((a, b) => a.localeCompare(b, "ru"));
  }, [tasks, rows]);

  const taskOptions = useMemo(
    () => tasks.map((t) => ({ phase: t.phase, task_name: t.task_name })),
    [tasks],
  );

  const addButton = (
    <button
      type="button"
      onClick={() => setShowAdd(true)}
      className="bg-accent text-white text-xs font-medium rounded-pill px-3 py-1.5 hover:bg-accent/90 min-h-[36px]"
      data-testid="add-labor-btn"
    >
      + Добавить
    </button>
  );

  const modal = showAdd && (
    <AddItemModal
      kind="labor"
      phaseOptions={phaseOptions}
      taskOptions={taskOptions}
      onClose={() => setShowAdd(false)}
      onSubmit={async (payload) => {
        await api.addLabor(projectId, payload as Parameters<typeof api.addLabor>[1]);
        onAdded();
      }}
    />
  );

  if (rows.length === 0) {
    return (
      <div className="flex flex-col gap-3" data-testid="labor-tab">
        <div className="flex justify-end">{addButton}</div>
        <div
          className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center"
          data-testid="labor-empty"
        >
          Нет данных по трудозатратам
        </div>
        {modal}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="labor-tab">
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
          const sumPlan = rows.reduce((s, r) => s + r.payroll_plan, 0);
          const sumActual = rows.reduce((s, r) => s + r.payroll_actual, 0);
          const selected = selectedItem === "__all__"
            ? null
            : rows.find((r) => r.specialty === selectedItem);
          const planScale = selected && sumPlan > 0 ? selected.payroll_plan / sumPlan : 1;
          const actualScale = selected && sumActual > 0 ? selected.payroll_actual / sumActual : 1;
          return (
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
                  category="labor"
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
        <LaborChart rows={rows} />
      ) : (
        <div className="bg-surface border border-border rounded-card overflow-x-auto shadow-card">
          <table className="w-full text-sm min-w-[760px]">
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
      {modal}
    </div>
  );
}
