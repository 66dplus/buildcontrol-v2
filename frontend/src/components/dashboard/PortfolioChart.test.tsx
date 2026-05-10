import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  PortfolioChart,
  shortenProjectName,
  buildPortfolioRows,
} from "./PortfolioChart";
import type { DashboardProject } from "../../lib/api";

// jsdom can't lay out SVG; mock ResponsiveContainer so children mount cleanly.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="rc-container" style={{ width: 600, height: 300 }}>
        {children}
      </div>
    ),
  };
});

function makeProjects(n: number): DashboardProject[] {
  return Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    name: `Проект ${i + 1}`,
    materials_plan: 10_000_000,
    materials_actual: 11_000_000,
    labor_plan: 5_000_000,
    labor_actual: 5_200_000,
    equipment_plan: 2_000_000,
    equipment_actual: 2_100_000,
    total_plan: 17_000_000,
    total_actual: 18_300_000,
    variance_pct: 7.6,
    phase_count: 3,
  }));
}

describe("PortfolioChart", () => {
  it("renders the empty state when no projects given", () => {
    render(<PortfolioChart projects={[]} />);
    expect(screen.getByTestId("portfolio-chart-empty")).toHaveTextContent(
      "Нет проектов для отображения",
    );
  });

  it("renders the chart container and title when projects exist", () => {
    render(<PortfolioChart projects={makeProjects(2)} />);
    expect(screen.getByTestId("portfolio-chart")).toBeInTheDocument();
    expect(screen.getByText("По проектам")).toBeInTheDocument();
    expect(screen.getByTestId("rc-container")).toBeInTheDocument();
  });
});

describe("shortenProjectName", () => {
  it("returns the original name when ≤ 18 chars", () => {
    expect(shortenProjectName("Короткое")).toBe("Короткое");
    expect(shortenProjectName("12345678901234567")).toBe("12345678901234567"); // 17
  });

  it("truncates names longer than 18 chars to 16 + ellipsis", () => {
    const result = shortenProjectName("Очень-очень длинное название");
    expect(result.endsWith("…")).toBe(true);
    expect(result.length).toBe(17); // 16 + ellipsis
  });
});

describe("buildPortfolioRows", () => {
  it("maps each project to one chart row with shortened name", () => {
    const rows = buildPortfolioRows(makeProjects(3));
    expect(rows).toHaveLength(3);
    expect(rows[0]).toMatchObject({
      name: "Проект 1",
      plan: 17_000_000,
      actual: 18_300_000,
      mat_plan: 10_000_000,
      lab_plan: 5_000_000,
      eq_plan: 2_000_000,
    });
  });
});
