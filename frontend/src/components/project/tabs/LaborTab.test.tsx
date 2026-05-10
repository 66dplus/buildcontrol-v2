import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LaborTab } from "./LaborTab";
import type { LaborRow } from "../../../lib/api";

function row(overrides: Partial<LaborRow> = {}): LaborRow {
  return {
    id: 1,
    project_id: 7,
    phase: "Каркас",
    task_name: "Армирование",
    specialty: "Арматурщик",
    rate: 500,
    hours_plan: 200,
    payroll_plan: 100_000,
    hours_actual: 210,
    payroll_actual: 105_000,
    ...overrides,
  };
}

describe("LaborTab", () => {
  it("renders empty state when no rows", () => {
    render(<LaborTab rows={[]} />);
    expect(screen.getByTestId("labor-empty")).toBeInTheDocument();
  });

  it("renders one row per labor entry", () => {
    render(<LaborTab rows={[row({ id: 1 }), row({ id: 2, specialty: "Бетонщик" })]} />);
    expect(screen.getByTestId("labor-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("labor-row-2")).toBeInTheDocument();
    expect(screen.getByText("Арматурщик")).toBeInTheDocument();
    expect(screen.getByText("Бетонщик")).toBeInTheDocument();
  });

  it("highlights overrun rows when payroll variance > 15%", () => {
    render(
      <LaborTab
        rows={[
          row({ id: 1, payroll_plan: 100, payroll_actual: 110 }),
          row({ id: 2, payroll_plan: 100, payroll_actual: 200 }),
        ]}
      />,
    );
    expect(screen.getByTestId("labor-row-1").className).not.toContain("bg-warning");
    expect(screen.getByTestId("labor-row-2").className).toContain("bg-warning");
  });
});
