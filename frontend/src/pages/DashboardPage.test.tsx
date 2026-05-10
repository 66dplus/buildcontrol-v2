import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DashboardPage } from "./DashboardPage";
import type { DashboardSummary } from "../lib/api";

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

const EMPTY_TIMELINE = { plan_series: [], actual_series: [] };

function summary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    kpi: {
      total_plan: 30_000_000,
      total_actual: 31_500_000,
      anomaly_count: 0,
      behind_count: 0,
    },
    projects: [
      {
        id: 1,
        name: "Торговый центр",
        materials_plan: 18_000_000,
        materials_actual: 18_600_000,
        labor_plan: 9_000_000,
        labor_actual: 9_200_000,
        equipment_plan: 3_000_000,
        equipment_actual: 3_100_000,
        total_plan: 30_000_000,
        total_actual: 30_900_000,
        variance_pct: 3.0,
        phase_count: 2,
      },
    ],
    ...overrides,
  };
}

function mockEndpoints(summaryData = summary()) {
  globalThis.fetch = vi.fn().mockImplementation(async (input: RequestInfo) => {
    const url = String(input);
    if (/\/api\/dashboard\/budget-timeline/.test(url)) {
      return new Response(JSON.stringify(EMPTY_TIMELINE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (/\/api\/dashboard\/summary/.test(url)) {
      return new Response(JSON.stringify(summaryData), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("not mocked: " + url, { status: 500 });
  }) as unknown as typeof fetch;
}

function renderPage() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("DashboardPage", () => {
  it("shows the loading state immediately on mount", () => {
    mockEndpoints();
    renderPage();
    expect(screen.getByTestId("dashboard-loading")).toBeInTheDocument();
  });

  it("renders KPI tiles, timeline chart and table after data loads", async () => {
    mockEndpoints();
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("dashboard")).toBeInTheDocument(),
    );
    const tiles = screen.getAllByTestId("kpi-tile");
    expect(tiles).toHaveLength(3);
    expect(tiles[0]).toHaveTextContent("Итого план");
    expect(tiles[1]).toHaveTextContent("Итого факт");
    expect(tiles[2]).toHaveTextContent("Отклонение");
    expect(screen.getByTestId("project-table")).toBeInTheDocument();
    expect(screen.getByText("Торговый центр")).toBeInTheDocument();
  });

  it("shows on-track banner when behind_count is zero", async () => {
    mockEndpoints(summary({ kpi: { total_plan: 100, total_actual: 100, anomaly_count: 0, behind_count: 0 } }));
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("dashboard")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("on-track-banner")).toBeInTheDocument();
    expect(screen.queryByTestId("behind-banner")).not.toBeInTheDocument();
  });

  it("renders the behind banner with the count when behind_count > 0", async () => {
    mockEndpoints(
      summary({ kpi: { total_plan: 100, total_actual: 200, anomaly_count: 3, behind_count: 2 } }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByTestId("behind-banner")).toBeInTheDocument());
    const banner = screen.getByTestId("behind-banner");
    expect(banner).toHaveTextContent("2");
    expect(banner).toHaveTextContent(/отстают от графика/i);
  });

  it("renders an error state when the request fails", async () => {
    globalThis.fetch = vi.fn().mockImplementation(
      async () =>
        new Response("boom", {
          status: 500,
          headers: { "Content-Type": "text/plain" },
        }),
    ) as unknown as typeof fetch;
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("dashboard-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("dashboard-error")).toHaveTextContent(/Не удалось/);
  });

  it("singularises 'проект' for one project", async () => {
    mockEndpoints();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Портфель: 1 проект$/)).toBeInTheDocument(),
    );
  });
});
