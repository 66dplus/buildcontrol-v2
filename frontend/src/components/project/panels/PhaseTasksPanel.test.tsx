import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PhaseTasksPanel } from "./PhaseTasksPanel";
import type { TaskRow } from "../../../lib/api";

function task(overrides: Partial<TaskRow> = {}): TaskRow {
  return {
    id: 1,
    project_id: 7,
    bitrix_task_id: null,
    bitrix_element_id: null,
    phase: "Каркас",
    task_name: "Армирование",
    date_start_plan: "2026-04-01",
    date_end_plan: "2026-04-30",
    date_start_actual: null,
    date_end_actual: null,
    budget_plan: 1_000_000,
    budget_actual: 1_050_000,
    completion_pct: 80,
    stage_id: null,
    stage_name: "В работе",
    ...overrides,
  };
}

describe("PhaseTasksPanel", () => {
  it("shows phase name and total task count", () => {
    render(
      <PhaseTasksPanel
        phaseName="Каркас"
        tasks={[task({ id: 1 }), task({ id: 2, task_name: "Бетонирование" })]}
      />,
    );
    expect(screen.getByTestId("phase-tasks-panel")).toBeInTheDocument();
    expect(screen.getByText("Каркас")).toBeInTheDocument();
    expect(screen.getByText(/2 задач/i)).toBeInTheDocument();
  });

  it("singularises 'задача' for one task", () => {
    render(<PhaseTasksPanel phaseName="Один" tasks={[task()]} />);
    expect(screen.getByText(/1 задача/i)).toBeInTheDocument();
  });

  it("renders one button per task with stage badge", () => {
    render(
      <PhaseTasksPanel
        phaseName="Каркас"
        tasks={[task({ id: 1, task_name: "T1" }), task({ id: 2, task_name: "T2" })]}
      />,
    );
    expect(screen.getByTestId("task-1")).toBeInTheDocument();
    expect(screen.getByTestId("task-2")).toBeInTheDocument();
  });

  it("clicking a task swaps to TaskDetailPanel inside the same panel", async () => {
    const user = userEvent.setup();
    render(
      <PhaseTasksPanel
        phaseName="Каркас"
        tasks={[task({ id: 1, task_name: "Армирование" })]}
      />,
    );
    await user.click(screen.getByTestId("task-1"));
    expect(screen.getByTestId("task-detail-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("phase-tasks-panel")).not.toBeInTheDocument();
  });

  it("the back button returns to the task list", async () => {
    const user = userEvent.setup();
    render(<PhaseTasksPanel phaseName="K" tasks={[task({ id: 1 })]} />);
    await user.click(screen.getByTestId("task-1"));
    await user.click(screen.getByTestId("task-back"));
    expect(screen.getByTestId("phase-tasks-panel")).toBeInTheDocument();
  });
});
