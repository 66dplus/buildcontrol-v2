import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type DashboardSummary } from "../lib/api";
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

function PlanVsFactBars({ plan, actual }: { plan: number; actual: number }) {
  const max = Math.max(plan, actual, 1);
  const planPct = Math.round((plan / max) * 100);
  const actualPct = Math.round((actual / max) * 100);
  const overrun = actual > plan;
  return (
    <div
      className="bg-surface border border-border rounded-card p-5 shadow-card"
      data-testid="plan-vs-fact-bars"
    >
      <div className="flex items-end justify-around gap-6 h-48">
        <div className="flex flex-col items-center gap-2 w-full max-w-[100px]">
          <div className="relative w-16 md:w-20 h-40 bg-bg rounded-card overflow-hidden border border-border">
            <div
              className="absolute bottom-0 left-0 right-0 bg-slate-300"
              style={{ height: `${planPct}%` }}
            />
          </div>
          <div className="text-center">
            <p className="text-xs text-muted">План</p>
            <p className="text-sm font-medium text-ink">{formatMoney(plan, { compact: true })}</p>
          </div>
        </div>
        <div className="flex flex-col items-center gap-2 w-full max-w-[100px]">
          <div className="relative w-16 md:w-20 h-40 bg-bg rounded-card overflow-hidden border border-border">
            <div
              className={`absolute bottom-0 left-0 right-0 ${overrun ? "bg-warning" : "bg-accent"}`}
              style={{ height: `${actualPct}%` }}
            />
          </div>
          <div className="text-center">
            <p className="text-xs text-muted">Факт</p>
            <p className={`text-sm font-medium ${overrun ? "text-warning" : "text-ink"}`}>
              {formatMoney(actual, { compact: true })}
              {overrun ? " ⚠" : ""}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export function DashboardPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const navigate = useNavigate();

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

  const behindProjects = projects.filter((p) => p.is_behind);
  const behindNames = behindProjects.map((p) => p.name).join(", ");
  const askAi = () => {
    const msg = behindProjects.length > 0
      ? `У нас отстают проекты: ${behindNames}. По каждому: на сколько дней опаздывают, сколько бюджета потрачено и на каком этапе именно отстают сроки.`
      : "Расскажи общую картину по проектам.";
    navigate("/ai", { state: { autoMessage: msg } });
  };

  return (
    <div className="flex flex-col gap-6 md:gap-8" data-testid="dashboard">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-xl md:text-2xl text-ink">Дашборд</h1>
          <p className="text-muted text-sm">
            Портфель: {projects.length} {pluralProjects(projects.length)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate("/projects/new")}
          className="bg-accent text-white text-sm font-medium rounded-pill px-5 py-2 hover:bg-accent/90"
          data-testid="create-project-cta"
        >
          + Создать проект
        </button>
      </div>

      {/* Budget section: KPI tiles + bars + alert side-by-side */}
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

        <div className="grid grid-cols-1 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-4">
          <PlanVsFactBars plan={kpi.total_plan} actual={kpi.total_actual} />

          {kpi.behind_count > 0 ? (
            <div
              className="bg-surface border border-warning/40 rounded-card p-5 shadow-card flex flex-col justify-center"
              data-testid="behind-banner"
            >
              <p className="text-ink font-medium text-base">
                {kpi.behind_count} {pluralProjects(kpi.behind_count)} отстают от графика
              </p>
              <p className="text-muted text-sm mt-1">
                Есть задачи с истёкшим плановым сроком и незавершённым прогрессом.
              </p>
              <button
                type="button"
                onClick={askAi}
                className="inline-block self-start mt-3 text-accent text-sm hover:underline min-h-11"
              >
                Спросить AI-ассистента →
              </button>
            </div>
          ) : (
            <div
              className="bg-surface border border-border rounded-card p-5 shadow-card flex flex-col justify-center text-center"
              data-testid="on-track-banner"
            >
              <p className="text-ink font-medium">Все проекты идут по графику</p>
              <p className="text-muted text-sm mt-1">Просроченных задач не обнаружено.</p>
            </div>
          )}
        </div>
      </section>

      {/* Project table */}
      <ProjectTable projects={projects} />
    </div>
  );
}
