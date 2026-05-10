import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ProjectTable } from "./ProjectTable";
import type { DashboardProject } from "../../lib/api";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

function project(overrides: Partial<DashboardProject> = {}): DashboardProject {
  return {
    id: 1,
    name: "Проект А",
    materials_plan: 10_000_000,
    materials_actual: 10_500_000,
    labor_plan: 5_000_000,
    labor_actual: 5_200_000,
    equipment_plan: 2_000_000,
    equipment_actual: 2_100_000,
    total_plan: 17_000_000,
    total_actual: 17_800_000,
    variance_pct: 4.7,
    phase_count: 2,
    ...overrides,
  };
}

function renderTable(projects: DashboardProject[]) {
  return render(
    <MemoryRouter>
      <ProjectTable projects={projects} />
    </MemoryRouter>,
  );
}

describe("ProjectTable", () => {
  it("renders empty state when no projects", () => {
    renderTable([]);
    expect(screen.getByTestId("project-table-empty")).toHaveTextContent(
      "Нет проектов в портфеле",
    );
  });

  it("renders one row per project with name and budget", () => {
    renderTable([
      project({ id: 1, name: "Один" }),
      project({ id: 2, name: "Два", total_plan: 5_000_000, total_actual: 5_100_000 }),
    ]);
    expect(screen.getByTestId("project-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("project-row-2")).toBeInTheDocument();
    expect(screen.getByText("Один")).toBeInTheDocument();
    expect(screen.getByText("Два")).toBeInTheDocument();
  });

  it("classifies variance ≤ 0% as 'В норме' (success)", () => {
    renderTable([project({ id: 1, name: "OK", variance_pct: -2 })]);
    const row = screen.getByTestId("project-row-1");
    expect(within(row).getByText("В норме")).toBeInTheDocument();
  });

  it("classifies variance 1–15% as 'Внимание' (amber)", () => {
    renderTable([project({ id: 1, name: "Watch", variance_pct: 8 })]);
    const row = screen.getByTestId("project-row-1");
    expect(within(row).getByText("Внимание")).toBeInTheDocument();
  });

  it("classifies variance > 15% as 'Перерасход' and adds amber border", () => {
    renderTable([project({ id: 1, name: "Bad", variance_pct: 22 })]);
    const row = screen.getByTestId("project-row-1");
    expect(within(row).getByText("Перерасход")).toBeInTheDocument();
    expect(row.className).toContain("border-l-warning");
  });

  it("sorts by variance desc by default (worst project first)", () => {
    renderTable([
      project({ id: 1, name: "Low", variance_pct: 2 }),
      project({ id: 2, name: "High", variance_pct: 30 }),
      project({ id: 3, name: "Mid", variance_pct: 10 }),
    ]);
    const rows = screen.getAllByRole("row").slice(1); // skip header
    expect(rows[0]).toHaveAttribute("data-testid", "project-row-2");
    expect(rows[1]).toHaveAttribute("data-testid", "project-row-3");
    expect(rows[2]).toHaveAttribute("data-testid", "project-row-1");
  });

  it("toggles sort direction when clicking the active sort header", async () => {
    const user = userEvent.setup();
    renderTable([
      project({ id: 1, name: "Low", variance_pct: 2 }),
      project({ id: 2, name: "High", variance_pct: 30 }),
    ]);
    // Initially desc → first row is High (id 2)
    let rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveAttribute("data-testid", "project-row-2");

    await user.click(screen.getByRole("button", { name: /Sort by Отклонение/i }));
    rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveAttribute("data-testid", "project-row-1");
  });

  it("sorts by name asc when name header clicked first time", async () => {
    const user = userEvent.setup();
    renderTable([
      project({ id: 1, name: "Б", variance_pct: 5 }),
      project({ id: 2, name: "А", variance_pct: 5 }),
    ]);
    await user.click(screen.getByRole("button", { name: /Sort by Проект/i }));
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveAttribute("data-testid", "project-row-2"); // А
    expect(rows[1]).toHaveAttribute("data-testid", "project-row-1"); // Б
  });

  it("navigates to /projects/:id on row click", async () => {
    const user = userEvent.setup();
    mockNavigate.mockClear();
    renderTable([project({ id: 42, name: "Click me" })]);
    await user.click(screen.getByTestId("project-row-42"));
    expect(mockNavigate).toHaveBeenCalledWith("/projects/42");
  });

  it("formats positive variance with a leading +", () => {
    renderTable([project({ id: 1, variance_pct: 7.5 })]);
    expect(screen.getByText("+7.5%")).toBeInTheDocument();
  });
});
