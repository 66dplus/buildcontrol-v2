import { useState } from "react";
import {
  BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import type { DashboardProject } from "../../lib/api";
import { formatMoney } from "../../lib/format";

interface PortfolioChartProps {
  projects: DashboardProject[];
  height?: number;
}

interface ChartRow {
  name: string;
  fullName: string;
  plan: number;
  actual: number;
  mat_plan: number;
  lab_plan: number;
  eq_plan: number;
  mat_actual: number;
  lab_actual: number;
  eq_actual: number;
}

export function shortenProjectName(name: string): string {
  return name.length > 18 ? `${name.slice(0, 16)}…` : name;
}

export function buildPortfolioRows(projects: DashboardProject[]): ChartRow[] {
  return projects.map((p) => ({
    name: shortenProjectName(p.name),
    fullName: p.name,
    plan: p.total_plan,
    actual: p.total_actual,
    mat_plan: p.materials_plan,
    lab_plan: p.labor_plan,
    eq_plan: p.equipment_plan,
    mat_actual: p.materials_actual,
    lab_actual: p.labor_actual,
    eq_actual: p.equipment_actual,
  }));
}

const COMPACT = (v: number) => formatMoney(v, { compact: true });

function CustomTooltip({ active, payload, label }: { active?: boolean; payload?: any[]; label?: string }) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload as ChartRow | undefined;
  if (!row) return null;
  const overrun = row.actual > row.plan;
  return (
    <div className="bg-surface border border-border rounded-card p-3 shadow-card text-xs w-64">
      <p className="font-medium text-ink mb-2 text-sm">{row.fullName || label}</p>
      <div className="space-y-1">
        <div className="flex justify-between">
          <span className="text-muted">План итого</span>
          <span className="text-ink font-medium">{COMPACT(row.plan)}</span>
        </div>
        <div className={`flex justify-between ${overrun ? "text-warning font-medium" : ""}`}>
          <span className={overrun ? "text-warning" : "text-muted"}>Факт итого{overrun ? " ⚠" : ""}</span>
          <span>{COMPACT(row.actual)}</span>
        </div>
        <hr className="border-border my-1" />
        <div className="flex justify-between text-muted">
          <span>Материалы план / факт</span>
          <span>{COMPACT(row.mat_plan)} / {COMPACT(row.mat_actual)}</span>
        </div>
        <div className="flex justify-between text-muted">
          <span>Труд план / факт</span>
          <span>{COMPACT(row.lab_plan)} / {COMPACT(row.lab_actual)}</span>
        </div>
        <div className="flex justify-between text-muted">
          <span>Техника план / факт</span>
          <span>{COMPACT(row.eq_plan)} / {COMPACT(row.eq_actual)}</span>
        </div>
      </div>
    </div>
  );
}

type ChartType = "bar" | "line";

export function PortfolioChart({ projects, height = 300 }: PortfolioChartProps) {
  const [chartType, setChartType] = useState<ChartType>("bar");

  if (projects.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center" data-testid="portfolio-chart-empty">
        Нет проектов для отображения
      </div>
    );
  }

  const rows = buildPortfolioRows(projects);

  const axisProps = {
    tickFormatter: COMPACT,
    tick: { fill: "#78716c", fontSize: 11 },
    axisLine: { stroke: "#e5e7eb" },
    tickLine: false as const,
    width: 70,
  };

  const xProps = {
    dataKey: "name" as const,
    tick: { fill: "#78716c", fontSize: 11 },
    axisLine: { stroke: "#e5e7eb" },
    tickLine: false as const,
  };

  return (
    <div className="bg-surface border border-border rounded-card p-5 shadow-card" data-testid="portfolio-chart">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-heading text-base text-ink">По проектам</h2>
        <div className="flex gap-1 p-0.5 bg-bg border border-border rounded-pill text-xs">
          {(["bar", "line"] as ChartType[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setChartType(t)}
              className={`px-3 py-1 rounded-pill transition-colors ${
                chartType === t ? "bg-surface text-ink font-medium shadow-card" : "text-muted hover:text-ink"
              }`}
            >
              {t === "bar" ? "Столбцы" : "Линии"}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={height}>
        {chartType === "bar" ? (
          <BarChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 4 }} barCategoryGap="30%">
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
            <XAxis {...xProps} />
            <YAxis {...axisProps} />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: "#fafaf9" }} />
            <Legend wrapperStyle={{ fontSize: 12, color: "#78716c" }} iconType="circle" />
            <Bar dataKey="plan" name="План" fill="#9bc8e8" radius={[4, 4, 0, 0]} />
            <Bar dataKey="actual" name="Факт" fill="#3ba6f1" radius={[4, 4, 0, 0]} />
          </BarChart>
        ) : (
          <LineChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
            <XAxis {...xProps} />
            <YAxis {...axisProps} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 12, color: "#78716c" }} iconType="circle" />
            <Line dataKey="plan" name="План" stroke="#9bc8e8" strokeWidth={2} dot={{ r: 4, fill: "#9bc8e8" }} />
            <Line dataKey="actual" name="Факт" stroke="#3ba6f1" strokeWidth={2} dot={{ r: 4, fill: "#3ba6f1" }} />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
