import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StagesTab, buildPhaseSummaries } from "./StagesTab";
import { SidePanelProvider } from "../../../contexts/SidePanelContext";
import { SidePanel } from "../../SidePanel";
import type { TaskRow } from "../../../lib/api";

function task(overrides: Partial<TaskRow> = {}): TaskRow {
  return {
    id: 1,
    project_id: 7,
    bitrix_task_id: null,
    bitrix_element_id: null,
    phase: "Каркас",
    task_name: "Армирование",
    date_start_plan: null,
    date_end_plan: null,
    date_start_actual: null,
    date_end_actual: null,
    budget_plan: 1_000_000,
    budget_actual: 1_050_000,
    completion_pct: 80,
    stage_id: null,
    stage_name: null,
    ...overrides,
  };
}

function renderWithPanel(tasks: TaskRow[]) {
  return render(
    <SidePanelProvider>
      <StagesTab tasks={tasks} />
      <SidePanel />
    </SidePanelProvider>,
  );
}

describe("StagesTab", () => {
  it("renders empty state when no tasks", () => {
    renderWithPanel([]);
    expect(screen.getByTestId("stages-empty")).toBeInTheDocument();
  });

  it("groups tasks by phase into one row each", () => {
    renderWithPanel([
      task({ id: 1, phase: "Каркас", task_name: "T1" }),
      task({ id: 2, phase: "Каркас", task_name: "T2" }),
      task({ id: 3, phase: "Отделка", task_name: "T3" }),
    ]);
    expect(screen.getByTestId("stage-row-Каркас")).toBeInTheDocument();
    expect(screen.getByTestId("stage-row-Отделка")).toBeInTheDocument();
  });

  it("highlights overrun phases with the amber left border", () => {
    renderWithPanel([
      task({ id: 1, phase: "Bad", budget_plan: 100, budget_actual: 200, completion_pct: 50 }),
    ]);
    const row = screen.getByTestId("stage-row-Bad");
    expect(row.className).toContain("border-l-warning");
  });

  it("clicking a phase row opens the SidePanel with the task list", async () => {
    const user = userEvent.setup();
    renderWithPanel([
      task({ id: 1, phase: "Каркас", task_name: "Армирование" }),
      task({ id: 2, phase: "Каркас", task_name: "Бетонирование" }),
    ]);
    await user.click(screen.getByTestId("stage-row-Каркас"));
    expect(screen.getByTestId("phase-tasks-panel")).toBeInTheDocument();
    expect(screen.getByText("Армирование")).toBeInTheDocument();
    expect(screen.getByText("Бетонирование")).toBeInTheDocument();
  });
});

describe("buildPhaseSummaries", () => {
  it("aggregates plan/actual and averages completion per phase", () => {
    const result = buildPhaseSummaries([
      task({ id: 1, phase: "A", budget_plan: 100, budget_actual: 110, completion_pct: 50 }),
      task({ id: 2, phase: "A", budget_plan: 200, budget_actual: 250, completion_pct: 100 }),
      task({ id: 3, phase: "B", budget_plan: 50, budget_actual: 50, completion_pct: 25 }),
    ]);
    const a = result.find((p) => p.name === "A")!;
    expect(a.taskCount).toBe(2);
    expect(a.totalPlan).toBe(300);
    expect(a.totalActual).toBe(360);
    expect(a.avgCompletion).toBe(75); // (50 + 100) / 2

    const b = result.find((p) => p.name === "B")!;
    expect(b.taskCount).toBe(1);
    expect(b.avgCompletion).toBe(25);
  });

  it("sorts phases alphabetically (ru locale)", () => {
    const result = buildPhaseSummaries([
      task({ id: 1, phase: "Я" }),
      task({ id: 2, phase: "А" }),
      task({ id: 3, phase: "М" }),
    ]);
    expect(result.map((p) => p.name)).toEqual(["А", "М", "Я"]);
  });
});
