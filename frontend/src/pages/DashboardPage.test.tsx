import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DashboardPage } from "./DashboardPage";
import type { DashboardSummary } from "../lib/api";

// Mock recharts ResponsiveContainer (jsdom can't measure SVG width).
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

function summary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    kpi: {
      total_plan: 30_000_000,
      total_actual: 31_500_000,
      anomaly_count: 0,
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

function mockFetch(body: unknown, status = 200) {
  globalThis.fetch = vi.fn().mockImplementation(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
  ) as unknown as typeof fetch;
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
    mockFetch(summary());
    renderPage();
    expect(screen.getByTestId("dashboard-loading")).toBeInTheDocument();
  });

  it("renders KPI tiles, chart and table after data loads", async () => {
    mockFetch(summary());
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("dashboard")).toBeInTheDocument(),
    );
    const tiles = screen.getAllByTestId("kpi-tile");
    expect(tiles).toHaveLength(3);
    expect(tiles[0]).toHaveTextContent("Бюджет план");
    expect(tiles[1]).toHaveTextContent("Бюджет факт");
    expect(tiles[2]).toHaveTextContent("Аномалии");
    expect(screen.getByTestId("portfolio-chart")).toBeInTheDocument();
    expect(screen.getByTestId("project-table")).toBeInTheDocument();
    expect(screen.getByText("Торговый центр")).toBeInTheDocument();
  });

  it("does NOT render the anomaly banner when count is zero", async () => {
    mockFetch(summary({ kpi: { total_plan: 100, total_actual: 100, anomaly_count: 0 } }));
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("dashboard")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("anomaly-banner")).not.toBeInTheDocument();
  });

  it("renders the anomaly banner with the count when count > 0", async () => {
    mockFetch(
      summary({ kpi: { total_plan: 100, total_actual: 200, anomaly_count: 3 } }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByTestId("anomaly-banner")).toBeInTheDocument());
    const banner = screen.getByTestId("anomaly-banner");
    expect(banner).toHaveTextContent("3");
    expect(banner).toHaveTextContent(/перерасход/i);
    expect(banner.getAttribute("href")).toBe("/ai");
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
    mockFetch(summary());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Портфель: 1 проект$/)).toBeInTheDocument(),
    );
  });
});
