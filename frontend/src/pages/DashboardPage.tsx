import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DashboardSummary, type DashboardProject } from "../lib/api";
import { formatMoney } from "../lib/format";
import { KpiTile } from "../components/dashboard/KpiTile";
import { ProjectTable } from "../components/dashboard/ProjectTable";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; summary: DashboardSummary }
  | { kind: "error"; message: string };

function pluralProjects(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return "проект";
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) return "проекта";
  return "проектов";
}

function BudgetBar({ label, plan, actual }: { label: string; plan: number; actual: number }) {
  const pct = plan > 0 ? Math.min((actual / plan) * 100, 150) : 0;
  const overrun = actual > plan;
  return (
    <div className="mb-4">
      <div className="flex justify-between text-sm mb-1.5">
        <span className="text-ink font-medium">{label}</span>
        <span className={overrun ? "text-warning font-medium" : "text-muted"}>
          {formatMoney(actual, { compact: true })} / {formatMoney(plan, { compact: true })}
          {overrun ? " ⚠" : ""}
        </span>
      </div>
      <div className="h-3 bg-bg rounded-full overflow-hidden border border-border">
        <div
          className={`h-full rounded-full ${overrun ? "bg-warning" : "bg-accent"}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  );
}

function BudgetComparisonPanel({ projects }: { projects: DashboardProject[] }) {
  const totalPlan   = projects.reduce((s, p) => s + p.total_plan, 0);
  const totalActual = projects.reduce((s, p) => s + p.total_actual, 0);
  const matPlan     = projects.reduce((s, p) => s + p.materials_plan, 0);
  const matActual   = projects.reduce((s, p) => s + p.materials_actual, 0);
  const labPlan     = projects.reduce((s, p) => s + p.labor_plan, 0);
  const labActual   = projects.reduce((s, p) => s + p.labor_actual, 0);
  const eqPlan      = projects.reduce((s, p) => s + p.equipment_plan, 0);
  const eqActual    = projects.reduce((s, p) => s + p.equipment_actual, 0);

  return (
    <div className="bg-surface border border-border rounded-card p-5 shadow-card">
      <BudgetBar label="Итого" plan={totalPlan} actual={totalActual} />
      <div className="border-t border-border my-3" />
      <BudgetBar label="Материалы" plan={matPlan} actual={matActual} />
      <BudgetBar label="Труд" plan={labPlan} actual={labActual} />
      <BudgetBar label="Техника" plan={eqPlan} actual={eqActual} />
    </div>
  );
}

export function DashboardPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    api.dashboardSummary()
      .then((summary) => {
        if (!cancelled) setState({ kind: "ready", summary });
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ kind: "error", message: err.message });
      });
    return () => { cancelled = true; };
  }, []);

  if (state.kind === "loading") {
    return <div data-testid="dashboard-loading" className="text-muted text-sm">Загрузка…</div>;
  }
  if (state.kind === "error") {
    return (
      <div data-testid="dashboard-error" className="bg-warning/10 border border-warning text-warning rounded-card p-4 text-sm">
        Не удалось загрузить дашборд: {state.message}
      </div>
    );
  }

  const { kpi, projects } = state.summary;
  const variancePct = kpi.total_plan
    ? ((kpi.total_actual - kpi.total_plan) / kpi.total_plan) * 100
    : 0;

  return (
    <div className="flex flex-col gap-8" data-testid="dashboard">
      <div>
        <h1 className="font-heading text-2xl text-ink">Дашборд</h1>
        <p className="text-muted text-sm">
          Портфель: {projects.length} {pluralProjects(projects.length)}
        </p>
      </div>

      {/* Budget section: KPI tiles + comparison bars */}
      <section>
        <h2 className="font-heading text-lg text-ink mb-4">Бюджет: план vs факт</h2>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-5">
          <KpiTile
            label="Итого план"
            value={formatMoney(kpi.total_plan, { compact: true })}
            hint="Совокупный бюджет план"
          />
          <KpiTile
            label="Итого факт"
            value={formatMoney(kpi.total_actual, { compact: true })}
            hint="Фактически освоено"
            tone={variancePct > 15 ? "warning" : variancePct > 0 ? "neutral" : "success"}
          />
          <KpiTile
            label="Отклонение"
            value={`${variancePct >= 0 ? "+" : ""}${variancePct.toFixed(1)}%`}
            hint={kpi.anomaly_count > 0 ? `${kpi.anomaly_count} проектов в перерасходе >15%` : "В рамках бюджета"}
            tone={variancePct > 15 ? "warning" : variancePct > 0 ? "neutral" : "success"}
          />
        </div>

        <BudgetComparisonPanel projects={projects} />
      </section>

      {/* Progress section */}
      <section>
        <h2 className="font-heading text-lg text-ink mb-4">Прогресс</h2>
        {kpi.behind_count > 0 ? (
          <div
            className="bg-surface border border-warning/40 rounded-card p-5 shadow-card"
            data-testid="behind-banner"
          >
            <p className="text-ink font-medium text-base">
              {kpi.behind_count} {pluralProjects(kpi.behind_count)} отстают от графика
            </p>
            <p className="text-muted text-sm mt-1">
              Есть задачи с истёкшим плановым сроком и незавершённым прогрессом.
            </p>
            <Link to="/ai" className="inline-block mt-3 text-accent text-sm hover:underline">
              Спросить AI-ассистента →
            </Link>
          </div>
        ) : (
          <div
            className="bg-surface border border-border rounded-card p-5 shadow-card text-center"
            data-testid="on-track-banner"
          >
            <p className="text-ink font-medium">Все проекты идут по графику</p>
            <p className="text-muted text-sm mt-1">Просроченных задач не обнаружено.</p>
          </div>
        )}
      </section>

      {/* Project table */}
      <ProjectTable projects={projects} />
    </div>
  );
}
