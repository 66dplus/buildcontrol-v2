import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type BudgetPhase,
  type EquipmentRow,
  type LaborRow,
  type MaterialRow,
  type TaskRow,
} from "../lib/api";
import { variancePct } from "../lib/format";
import { ProjectHeader } from "../components/project/ProjectHeader";
import { TabBar, type TabKey } from "../components/project/TabBar";
import { OverviewTab } from "../components/project/tabs/OverviewTab";
import { StagesTab } from "../components/project/tabs/StagesTab";
import { MaterialsTab } from "../components/project/tabs/MaterialsTab";
import { LaborTab } from "../components/project/tabs/LaborTab";
import { EquipmentTab } from "../components/project/tabs/EquipmentTab";

interface ProjectBundle {
  name: string;
  phases: BudgetPhase[];
  tasks: TaskRow[];
  materials: MaterialRow[];
  labor: LaborRow[];
  equipment: EquipmentRow[];
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; data: ProjectBundle }
  | { kind: "error"; message: string };

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [tab, setTab] = useState<TabKey>("overview");

  useEffect(() => {
    if (!Number.isFinite(projectId)) {
      setState({ kind: "error", message: "Некорректный ID проекта" });
      return;
    }
    let cancelled = false;
    setState({ kind: "loading" });
    Promise.all([
      api.projects(),
      api.phases(projectId),
      api.tasks(projectId),
      api.materials(projectId),
      api.labor(projectId),
      api.equipment(projectId),
    ])
      .then(([projects, phases, tasks, materials, labor, equipment]) => {
        if (cancelled) return;
        const proj = projects.find((p) => p.id === projectId);
        setState({
          kind: "ready",
          data: {
            name: proj?.name ?? `Проект #${projectId}`,
            phases,
            tasks,
            materials,
            labor,
            equipment,
          },
        });
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ kind: "error", message: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (state.kind === "loading") {
    return (
      <div data-testid="project-loading" className="text-muted text-sm">
        Загрузка проекта…
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div
        data-testid="project-error"
        className="bg-warning/10 border border-warning text-warning rounded-card p-4 text-sm"
      >
        Не удалось загрузить проект: {state.message}
      </div>
    );
  }

  const { data } = state;
  const totalPlan = data.phases.reduce((s, p) => s + p.total_plan, 0);
  const totalActual = data.phases.reduce((s, p) => s + p.total_actual, 0);
  const avgCompletion =
    data.tasks.length > 0
      ? data.tasks.reduce((s, t) => s + t.completion_pct, 0) / data.tasks.length
      : 0;
  const v = variancePct(totalPlan, totalActual);

  return (
    <div className="flex flex-col gap-5" data-testid="project-detail">
      <ProjectHeader
        name={data.name}
        totals={{
          total_plan: totalPlan,
          total_actual: totalActual,
          variance_pct: v,
          completion_pct: avgCompletion,
        }}
      />
      <TabBar active={tab} onChange={setTab} />
      <div data-testid={`tab-content-${tab}`}>
        {tab === "overview" && <OverviewTab phases={data.phases} />}
        {tab === "stages" && <StagesTab tasks={data.tasks} />}
        {tab === "materials" && <MaterialsTab materials={data.materials} />}
        {tab === "labor" && <LaborTab rows={data.labor} />}
        {tab === "equipment" && <EquipmentTab rows={data.equipment} />}
      </div>
    </div>
  );
}
