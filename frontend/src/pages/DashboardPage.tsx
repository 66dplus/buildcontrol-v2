import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DashboardSummary, type BudgetTimeline } from "../lib/api";
import { formatMoney } from "../lib/format";
import { KpiTile } from "../components/dashboard/KpiTile";
import { ProjectTable } from "../components/dashboard/ProjectTable";
import { BudgetTimelineChart } from "../components/BudgetTimelineChart";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; summary: DashboardSummary; timeline: BudgetTimeline }
  | { kind: "error"; message: string };

function pluralProjects(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return "проект";
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) return "проекта";
  return "проектов";
}

export function DashboardPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    Promise.all([api.dashboardSummary(), api.dashboardBudgetTimeline()])
      .then(([summary, timeline]) => {
        if (!cancelled) setState({ kind: "ready", summary, timeline });
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
  const { timeline } = state;
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

      {/* Budget section: KPI tiles + timeline chart */}
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

        <div className="bg-surface border border-border rounded-card p-4 shadow-card">
          <div className="flex items-center gap-4 text-xs text-muted mb-3">
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-6 h-0.5 bg-muted/50" style={{ borderTop: "2px dashed #94a3b8" }} />
              План
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-6 h-0.5 bg-accent" style={{ borderTop: "2px solid #3ba6f1" }} />
              Факт
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-warning" />
              Перерасход &gt;10%
            </span>
          </div>
          <BudgetTimelineChart timeline={timeline} height={260} />
        </div>
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
