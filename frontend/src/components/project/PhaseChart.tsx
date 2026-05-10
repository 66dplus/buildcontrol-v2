import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { BudgetPhase } from "../../lib/api";
import { formatMoney } from "../../lib/format";

interface PhaseChartProps {
  phases: BudgetPhase[];
  height?: number;
}

interface PhaseRow {
  name: string;
  План: number;
  Факт: number;
  overrun: boolean;
}

export function buildPhaseRows(phases: BudgetPhase[]): PhaseRow[] {
  return phases.map((p) => ({
    name: p.phase_name,
    План: p.total_plan,
    Факт: p.total_actual,
    overrun: p.total_plan > 0 && p.total_actual > p.total_plan * 1.05,
  }));
}

const COMPACT = (v: number) => formatMoney(v, { compact: true });

export function PhaseChart({ phases, height = 280 }: PhaseChartProps) {
  if (phases.length === 0) {
    return (
      <div
        className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center"
        data-testid="phase-chart-empty"
      >
        Нет этапов для отображения
      </div>
    );
  }

  const rows = buildPhaseRows(phases);

  return (
    <div
      className="bg-surface border border-border rounded-card p-5 shadow-card"
      data-testid="phase-chart"
    >
      <h2 className="font-heading text-lg text-ink mb-4">План vs факт по этапам</h2>
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
          <Legend wrapperStyle={{ fontSize: 12, color: "#78716c" }} iconType="circle" />
          <Bar dataKey="План" fill="#9ca3af" radius={[6, 6, 0, 0]} />
          <Bar dataKey="Факт" radius={[6, 6, 0, 0]}>
            {rows.map((row, idx) => (
              <Cell key={idx} fill={row.overrun ? "#e07c3e" : "#3ba6f1"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
