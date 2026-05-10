import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PhaseChart, buildPhaseRows } from "./PhaseChart";
import type { BudgetPhase } from "../../lib/api";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="rc-container" style={{ width: 600, height: 280 }}>
        {children}
      </div>
    ),
  };
});

function phase(overrides: Partial<BudgetPhase> = {}): BudgetPhase {
  return {
    id: 1,
    project_id: 1,
    phase_name: "Каркас",
    bitrix_element_id: null,
    materials_plan: 5_000_000,
    labor_plan: 3_000_000,
    equipment_plan: 1_000_000,
    total_plan: 9_000_000,
    materials_actual: 5_200_000,
    labor_actual: 3_100_000,
    equipment_actual: 1_050_000,
    total_actual: 9_350_000,
    ...overrides,
  };
}

describe("PhaseChart", () => {
  it("renders empty state when no phases", () => {
    render(<PhaseChart phases={[]} />);
    expect(screen.getByTestId("phase-chart-empty")).toBeInTheDocument();
  });

  it("renders chart container and title with phases", () => {
    render(<PhaseChart phases={[phase()]} />);
    expect(screen.getByTestId("phase-chart")).toBeInTheDocument();
    expect(screen.getByText("План vs факт по этапам")).toBeInTheDocument();
    expect(screen.getByTestId("rc-container")).toBeInTheDocument();
  });
});

describe("buildPhaseRows", () => {
  it("flags overrun rows when actual > plan * 1.05", () => {
    const rows = buildPhaseRows([
      phase({ phase_name: "ОК", total_plan: 100, total_actual: 100 }),
      phase({ phase_name: "Чуть-чуть", total_plan: 100, total_actual: 104 }),
      phase({ phase_name: "Бабах", total_plan: 100, total_actual: 130 }),
    ]);
    expect(rows[0].overrun).toBe(false);
    expect(rows[1].overrun).toBe(false); // within 5% tolerance
    expect(rows[2].overrun).toBe(true);
  });

  it("never flags overrun when plan is zero", () => {
    const rows = buildPhaseRows([
      phase({ phase_name: "Z", total_plan: 0, total_actual: 1_000_000 }),
    ]);
    expect(rows[0].overrun).toBe(false);
  });
});
