/**
 * Plan vs Actual budget chart over time.
 *
 * Renders two Recharts lines: dashed plan, solid actual.
 * Anomaly dots (red/yellow/green) mark deviations from plan.
 * A vertical "Today" reference line anchors the viewer in time.
 */
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import type { BudgetTimeline } from "../lib/api";

// ─── helpers ────────────────────────────────────────────────────────────────

const MONTHS_RU = ["Янв","Фев","Мар","Апр","Май","Июн","Июл","Авг","Сен","Окт","Ноя","Дек"];

function fmtDate(iso: string): string {
  const [y, m] = iso.split("-");
  return `${MONTHS_RU[parseInt(m, 10) - 1]} ${y?.slice(2)}`;
}

function fmtMoney(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M ₽`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(0)}k ₽`;
  return `${Math.round(n)} ₽`;
}

export type Category = "total" | "materials" | "labor" | "equipment";

interface ChartPoint {
  date: string;
  label: string;
  plan: number | null;
  actual: number | null;
  materials: number | null;
  labor: number | null;
  equipment: number | null;
  anomaly: "red" | "yellow" | "green" | null;
  variance_pct: number;
}

function buildChartData(timeline: BudgetTimeline): ChartPoint[] {
  const { plan_series, actual_series } = timeline;

  // All unique dates from both series, sorted
  const dateSet = new Set<string>([
    ...plan_series.map((p) => p.date),
    ...actual_series.map((a) => a.date),
  ]);
  const dates = [...dateSet].sort();

  // Step-interpolate plan: at each date, plan = last plan point at or before date
  const plansSorted = [...plan_series].sort((a, b) => a.date.localeCompare(b.date));

  function planAt(date: string): number {
    let last = 0;
    for (const p of plansSorted) {
      if (p.date <= date) last = p.total;
      else break;
    }
    return last;
  }

  // Ensure actual values never decrease (guard against bad snapshot data)
  const sortedActuals = [...actual_series].sort((a, b) => a.date.localeCompare(b.date));
  let runMax = 0, runMatMax = 0, runLabMax = 0, runEqMax = 0;
  const cleanedActuals = sortedActuals.map((a) => {
    runMax = Math.max(runMax, a.total ?? 0);
    runMatMax = Math.max(runMatMax, a.materials ?? 0);
    runLabMax = Math.max(runLabMax, a.labor ?? 0);
    runEqMax = Math.max(runEqMax, a.equipment ?? 0);
    return { ...a, total: runMax, materials: runMatMax, labor: runLabMax, equipment: runEqMax };
  });
  const actualMap = new Map(cleanedActuals.map((a) => [a.date, a]));

  return dates.map((date) => {
    const actual = actualMap.get(date);
    return {
      date,
      label: fmtDate(date),
      plan: plansSorted.length ? planAt(date) : null,
      actual: actual?.total ?? null,
      materials: actual?.materials ?? null,
      labor: actual?.labor ?? null,
      equipment: actual?.equipment ?? null,
      anomaly: actual?.anomaly ?? null,
      variance_pct: actual?.variance_pct ?? 0,
    };
  });
}

// ─── Anomaly dot ─────────────────────────────────────────────────────────────

const ANOMALY_COLOR: Record<string, string> = {
  red:    "#e07c3e",
  yellow: "#f59e0b",
  green:  "#22c55e",
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function AnomalyDot(props: any) {
  const { cx, cy, payload } = props as { cx?: number; cy?: number; payload?: ChartPoint };
  if (cx == null || cy == null) return null;
  if (!payload?.anomaly) {
    return <circle cx={cx} cy={cy} r={2} fill="#3ba6f1" opacity={0.4} />;
  }
  const color = ANOMALY_COLOR[payload.anomaly] ?? "#3ba6f1";
  return (
    <circle
      cx={cx}
      cy={cy}
      r={5}
      fill={color}
      stroke="white"
      strokeWidth={1.5}
    />
  );
}

// ─── Tooltip ─────────────────────────────────────────────────────────────────

function CustomTooltip({
  active,
  payload,
  category,
}: {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
  category: Category;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  if (p.actual == null && p.plan == null) return null;

  const variance = p.variance_pct;
  const overrun = variance > 0;
  const varColor = variance > 10 ? "#e07c3e" : variance > 0 ? "#f59e0b" : "#22c55e";

  return (
    <div className="bg-surface border border-border rounded-card px-3 py-2 text-xs shadow-sm max-w-[220px]">
      <p className="font-medium text-ink mb-1">{fmtDate(p.date)}</p>
      {p.plan != null && (
        <div className="flex justify-between gap-4 text-muted">
          <span>План</span><span className="text-ink">{fmtMoney(p.plan)}</span>
        </div>
      )}
      {p.actual != null && (
        <div className="flex justify-between gap-4">
          <span className="text-muted">Факт</span>
          <span className="text-ink">{fmtMoney(p.actual)}</span>
        </div>
      )}
      {p.actual != null && p.plan != null && p.plan > 0 && (
        <div className="flex justify-between gap-4 mt-1 pt-1 border-t border-border">
          <span className="text-muted">Отклонение</span>
          <span style={{ color: varColor }}>
            {overrun ? "+" : ""}{variance.toFixed(1)}%
          </span>
        </div>
      )}
      {category === "total" && p.actual != null && (
        <div className="mt-1 pt-1 border-t border-border space-y-0.5 text-muted">
          {p.materials != null && (
            <div className="flex justify-between gap-4">
              <span>🧱 Материалы</span><span>{fmtMoney(p.materials)}</span>
            </div>
          )}
          {p.labor != null && (
            <div className="flex justify-between gap-4">
              <span>👷 Труд</span><span>{fmtMoney(p.labor)}</span>
            </div>
          )}
          {p.equipment != null && (
            <div className="flex justify-between gap-4">
              <span>🚛 Техника</span><span>{fmtMoney(p.equipment)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface Props {
  timeline: BudgetTimeline;
  category?: Category;
  height?: number;
}

const CATEGORY_KEY: Record<Category, keyof ChartPoint> = {
  total:     "actual",
  materials: "materials",
  labor:     "labor",
  equipment: "equipment",
};

export function BudgetTimelineChart({ timeline, category = "total", height = 260 }: Props) {
  const data = buildChartData(timeline);
  const todayStr = new Date().toISOString().slice(0, 10);
  const todayLabel = fmtDate(todayStr);

  const actualKey = CATEGORY_KEY[category];

  // One tick label per month
  const seenMonths = new Set<string>();
  const monthTicks = data
    .filter((pt) => {
      const monthKey = pt.date.slice(0, 7);
      if (seenMonths.has(monthKey)) return false;
      seenMonths.add(monthKey);
      return true;
    })
    .map((pt) => pt.label);

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-muted text-sm"
        style={{ height }}
        data-testid="timeline-chart-empty"
      >
        Нет данных для отображения
      </div>
    );
  }

  return (
    <div data-testid="timeline-chart">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
          <XAxis
            dataKey="label"
            ticks={monthTicks}
            tick={{ fontSize: 11, fill: "#78716c" }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tickFormatter={fmtMoney}
            tick={{ fontSize: 11, fill: "#78716c" }}
            tickLine={false}
            axisLine={false}
            width={60}
          />
          <Tooltip
            content={<CustomTooltip category={category} />}
            cursor={{ stroke: "#e5e7eb", strokeWidth: 1 }}
          />

          {/* Today marker */}
          <ReferenceLine
            x={todayLabel}
            stroke="#78716c"
            strokeDasharray="4 2"
            label={{ value: "Сегодня", position: "insideTopRight", fontSize: 10, fill: "#78716c" }}
          />

          {/* Plan line (dashed) */}
          <Line
            dataKey="plan"
            name="План"
            stroke="#94a3b8"
            strokeWidth={1.5}
            strokeDasharray="6 3"
            dot={false}
            connectNulls
            isAnimationActive={false}
          />

          {/* Actual line with anomaly dots */}
          <Line
            dataKey={actualKey as string}
            name="Факт"
            stroke="#3ba6f1"
            strokeWidth={2}
            connectNulls
            isAnimationActive={false}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            dot={(props: any) => <AnomalyDot {...props} />}
            activeDot={{ r: 4, fill: "#3ba6f1" }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
