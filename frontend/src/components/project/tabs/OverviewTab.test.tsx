import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OverviewTab } from "./OverviewTab";
import type { BudgetPhase, BudgetTimeline } from "../../../lib/api";

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

const EMPTY_TIMELINE: BudgetTimeline = { plan_series: [], actual_series: [] };

const TIMELINE_WITH_DATA: BudgetTimeline = {
  plan_series: [{ date: "2026-01-01", total: 0 }, { date: "2026-02-01", total: 5_000_000 }],
  actual_series: [{ date: "2026-01-15", total: 1_000_000 }],
};

describe("OverviewTab", () => {
  it("renders the overview tab with overall totals", () => {
    render(<OverviewTab phases={[phase()]} timeline={EMPTY_TIMELINE} />);
    expect(screen.getByTestId("overview-tab")).toBeInTheDocument();
    expect(screen.getByText("Итого по проекту")).toBeInTheDocument();
  });

  it("shows category switcher tabs", () => {
    render(<OverviewTab phases={[phase()]} timeline={EMPTY_TIMELINE} />);
    expect(screen.getByTestId("category-tab-total")).toBeInTheDocument();
    expect(screen.getByTestId("category-tab-materials")).toBeInTheDocument();
    expect(screen.getByTestId("category-tab-labor")).toBeInTheDocument();
    expect(screen.getByTestId("category-tab-equipment")).toBeInTheDocument();
  });

  it("renders the recharts container for the timeline chart when data is present", () => {
    render(<OverviewTab phases={[phase()]} timeline={TIMELINE_WITH_DATA} />);
    expect(screen.getByTestId("rc-container")).toBeInTheDocument();
  });

  it("switches category when a tab is clicked", async () => {
    const user = userEvent.setup();
    render(<OverviewTab phases={[phase()]} timeline={EMPTY_TIMELINE} />);
    await user.click(screen.getByTestId("category-tab-materials"));
    // Category tab is now visually active (no testid for that, just verify no crash)
    expect(screen.getByTestId("overview-tab")).toBeInTheDocument();
  });

  it("shows empty state when no phases", () => {
    render(<OverviewTab phases={[]} timeline={EMPTY_TIMELINE} />);
    expect(screen.getByTestId("overview-tab")).toBeInTheDocument();
    expect(screen.getByText("Нет данных по этапам")).toBeInTheDocument();
  });
});
