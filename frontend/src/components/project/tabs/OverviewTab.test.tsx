import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { OverviewTab } from "./OverviewTab";
import type { BudgetPhase } from "../../../lib/api";

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

describe("OverviewTab", () => {
  it("renders both the chart and the breakdown table when phases exist", () => {
    render(<OverviewTab phases={[phase()]} />);
    expect(screen.getByTestId("overview-tab")).toBeInTheDocument();
    expect(screen.getByTestId("phase-chart")).toBeInTheDocument();
    expect(screen.getByTestId("phase-breakdown")).toBeInTheDocument();
  });

  it("highlights overrun phase rows with warning background", () => {
    render(
      <OverviewTab
        phases={[
          phase({ id: 1, phase_name: "OK", total_plan: 100, total_actual: 105 }),
          phase({ id: 2, phase_name: "Bad", total_plan: 100, total_actual: 130 }),
        ]}
      />,
    );
    expect(screen.getByTestId("phase-row-1").className).not.toContain("bg-warning");
    expect(screen.getByTestId("phase-row-2").className).toContain("bg-warning");
  });

  it("renders one table row per phase", () => {
    render(
      <OverviewTab
        phases={[
          phase({ id: 1, phase_name: "Каркас" }),
          phase({ id: 2, phase_name: "Отделка" }),
          phase({ id: 3, phase_name: "Кровля" }),
        ]}
      />,
    );
    const table = screen.getByTestId("phase-breakdown");
    const rows = within(table).getAllByRole("row");
    // 1 header row + 3 data rows
    expect(rows).toHaveLength(4);
  });
});
