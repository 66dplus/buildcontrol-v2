import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { DashboardProject } from "../../lib/api";
import { formatMoney } from "../../lib/format";

interface PortfolioChartProps {
  projects: DashboardProject[];
  height?: number;
}

interface ChartRow {
  name: string;
  Материалы: number;
  Труд: number;
  Техника: number;
  факт: number;
}

export function shortenProjectName(name: string): string {
  return name.length > 18 ? `${name.slice(0, 16)}…` : name;
}

export function buildPortfolioRows(projects: DashboardProject[]): ChartRow[] {
  return projects.map((p) => ({
    name: shortenProjectName(p.name),
    Материалы: p.materials_plan,
    Труд: p.labor_plan,
    Техника: p.equipment_plan,
    факт: p.total_actual,
  }));
}

const COMPACT = (v: number) => formatMoney(v, { compact: true });

export function PortfolioChart({ projects, height = 320 }: PortfolioChartProps) {
  if (projects.length === 0) {
    return (
      <div
        className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center"
        data-testid="portfolio-chart-empty"
      >
        Нет проектов для отображения
      </div>
    );
  }

  const rows = buildPortfolioRows(projects);

  return (
    <div
      className="bg-surface border border-border rounded-card p-5 shadow-card"
      data-testid="portfolio-chart"
    >
      <h2 className="font-heading text-lg text-ink mb-4">Портфель проектов</h2>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fill: "#78716c", fontSize: 12 }}
            axisLine={{ stroke: "#e5e7eb" }}
            tickLine={false}
          />
          <YAxis
            tickFormatter={COMPACT}
            tick={{ fill: "#78716c", fontSize: 12 }}
            axisLine={{ stroke: "#e5e7eb" }}
            tickLine={false}
            width={70}
          />
          <Tooltip
            formatter={(value) => COMPACT(Number(value))}
            cursor={{ fill: "#fafaf9" }}
          />
          <Legend
            wrapperStyle={{ fontSize: 12, color: "#78716c" }}
            iconType="circle"
          />
          <Bar dataKey="Материалы" stackId="plan" fill="#3ba6f1" radius={[0, 0, 0, 0]} />
          <Bar dataKey="Труд" stackId="plan" fill="#9bc8e8" />
          <Bar dataKey="Техника" stackId="plan" fill="#cfe6f7" radius={[6, 6, 0, 0]} />
          <Bar dataKey="факт" fill="#e07c3e" radius={[6, 6, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
