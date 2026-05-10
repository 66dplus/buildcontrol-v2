import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DashboardSummary } from "../lib/api";
import { formatMoney } from "../lib/format";
import { KpiTile } from "../components/dashboard/KpiTile";
import { PortfolioChart } from "../components/dashboard/PortfolioChart";
import { ProjectTable } from "../components/dashboard/ProjectTable";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; data: DashboardSummary }
  | { kind: "error"; message: string };

export function DashboardPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    api
      .dashboardSummary()
      .then((data) => {
        if (!cancelled) setState({ kind: "ready", data });
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ kind: "error", message: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading") {
    return (
      <div data-testid="dashboard-loading" className="text-muted text-sm">
        Загрузка дашборда…
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div
        data-testid="dashboard-error"
        className="bg-warning/10 border border-warning text-warning rounded-card p-4 text-sm"
      >
        Не удалось загрузить дашборд: {state.message}
      </div>
    );
  }

  const { kpi, projects } = state.data;
  const variancePct = kpi.total_plan
    ? ((kpi.total_actual - kpi.total_plan) / kpi.total_plan) * 100
    : 0;

  return (
    <div className="flex flex-col gap-6" data-testid="dashboard">
      <div>
        <h1 className="font-heading text-2xl text-ink">Дашборд</h1>
        <p className="text-muted text-sm">
          Портфель: {projects.length}{" "}
          {projects.length === 1 ? "проект" : "проектов"}
        </p>
      </div>

      {kpi.anomaly_count > 0 ? (
        <Link
          to="/ai"
          className="block bg-accent/10 border border-accent text-ink rounded-card px-4 py-3 text-sm hover:bg-accent/20 transition-colors"
          data-testid="anomaly-banner"
        >
          <span className="font-medium">{kpi.anomaly_count}</span>{" "}
          {kpi.anomaly_count === 1 ? "проект с перерасходом" : "проектов с перерасходом"} — открыть AI Assistant →
        </Link>
      ) : null}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <KpiTile
          label="Бюджет план"
          value={formatMoney(kpi.total_plan, { compact: true })}
          hint="Сумма по всем проектам"
        />
        <KpiTile
          label="Бюджет факт"
          value={formatMoney(kpi.total_actual, { compact: true })}
          hint={`${variancePct >= 0 ? "+" : ""}${variancePct.toFixed(1)}% к плану`}
          tone={variancePct > 15 ? "warning" : variancePct > 0 ? "neutral" : "success"}
        />
        <KpiTile
          label="Аномалии"
          value={String(kpi.anomaly_count)}
          hint="Перерасход > 15%"
          tone={kpi.anomaly_count > 0 ? "warning" : "success"}
        />
      </div>

      <PortfolioChart projects={projects} />

      <ProjectTable projects={projects} />
    </div>
  );
}
