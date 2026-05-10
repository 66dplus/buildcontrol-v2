import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProjectDetailPage } from "./ProjectDetailPage";
import { SidePanelProvider } from "../contexts/SidePanelContext";
import { SidePanel } from "../components/SidePanel";

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

const PROJECTS = [{ id: 7, name: "Тестовый проект", is_archived: 0 }];
const PHASES = [
  {
    id: 1, project_id: 7, phase_name: "Каркас", bitrix_element_id: null,
    materials_plan: 5_000_000, labor_plan: 3_000_000, equipment_plan: 1_000_000,
    total_plan: 9_000_000, materials_actual: 5_200_000, labor_actual: 3_100_000,
    equipment_actual: 1_050_000, total_actual: 9_350_000,
  },
];
const TASKS = [
  {
    id: 10, project_id: 7, bitrix_task_id: null, bitrix_element_id: null,
    phase: "Каркас", task_name: "Армирование",
    date_start_plan: "2026-04-01", date_end_plan: "2026-04-30",
    date_start_actual: null, date_end_actual: null,
    budget_plan: 2_000_000, budget_actual: 2_050_000,
    completion_pct: 80, stage_id: null, stage_name: "В работе",
  },
];
const MATERIALS = [
  {
    id: 100, project_id: 7, phase: "Каркас", task_name: "Армирование",
    material_name: "Арматура А500С", unit: "т",
    price_plan: 80_000, qty_plan: 10, cost_plan: 800_000,
    price_actual: 82_000, qty_bought: 10, qty_consumed: 8, qty_stock: 2,
    cost_actual: 820_000,
  },
];

function mockEndpoints({ projects = PROJECTS, phases = PHASES, tasks = TASKS, materials = MATERIALS, labor = [], equipment = [], whoamiHost = "standalone" } = {}) {
  globalThis.fetch = vi.fn().mockImplementation(async (input: RequestInfo) => {
    const url = String(input);
    const map: Array<[RegExp, unknown]> = [
      [/\/api\/whoami/, { user: "director", role: "director", host: whoamiHost, capabilities: [] }],
      [/\/api\/projects\/\d+\/phases$/, phases],
      [/\/api\/projects\/\d+\/tasks-full$/, tasks],
      [/\/api\/projects\/\d+\/materials-all/, materials],
      [/\/api\/projects\/\d+\/labor-all/, labor],
      [/\/api\/projects\/\d+\/equipment-all/, equipment],
      [/\/api\/projects$/, projects],
    ];
    for (const [re, body] of map) {
      if (re.test(url)) {
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response("not mocked: " + url, { status: 404 });
  }) as unknown as typeof fetch;
}

function renderPage(initial = "/projects/7") {
  return render(
    <SidePanelProvider>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>
      <SidePanel />
    </SidePanelProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("ProjectDetailPage", () => {
  it("shows the loading state immediately", () => {
    mockEndpoints();
    renderPage();
    expect(screen.getByTestId("project-loading")).toBeInTheDocument();
  });

  it("loads all bundle data and renders the header + Overview tab by default", async () => {
    mockEndpoints();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("project-detail")).toBeInTheDocument());
    expect(screen.getByText("Тестовый проект")).toBeInTheDocument();
    expect(screen.getByTestId("tab-content-overview")).toBeInTheDocument();
    expect(screen.getByTestId("phase-chart")).toBeInTheDocument();
  });

  it("switches tabs when a tab is clicked", async () => {
    mockEndpoints();
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("project-detail")).toBeInTheDocument());

    await user.click(screen.getByTestId("tab-stages"));
    expect(screen.getByTestId("tab-content-stages")).toBeInTheDocument();
    expect(screen.getByTestId("stages-tab")).toBeInTheDocument();

    await user.click(screen.getByTestId("tab-materials"));
    expect(screen.getByTestId("tab-content-materials")).toBeInTheDocument();
    expect(screen.getByTestId("materials-tab")).toBeInTheDocument();
  });

  it("clicking a phase row in Stages tab opens the SidePanel", async () => {
    mockEndpoints();
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("project-detail")).toBeInTheDocument());
    await user.click(screen.getByTestId("tab-stages"));
    await user.click(screen.getByTestId("stage-row-Каркас"));
    expect(screen.getByTestId("phase-tasks-panel")).toBeInTheDocument();
  });

  it("clicking a material row in Materials tab opens the SidePanel", async () => {
    mockEndpoints();
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("project-detail")).toBeInTheDocument());
    await user.click(screen.getByTestId("tab-materials"));
    await user.click(screen.getByTestId("material-row-100"));
    expect(screen.getByTestId("material-detail-panel")).toBeInTheDocument();
  });

  it("renders an error state when one of the endpoints fails", async () => {
    globalThis.fetch = vi.fn().mockImplementation(
      async () => new Response("nope", { status: 500 }),
    ) as unknown as typeof fetch;
    renderPage();
    await waitFor(() => expect(screen.getByTestId("project-error")).toBeInTheDocument());
  });

  it("falls back to 'Проект #ID' if the project is not in the projects list", async () => {
    mockEndpoints({ projects: [] });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("project-detail")).toBeInTheDocument());
    expect(screen.getByText("Проект #7")).toBeInTheDocument();
  });
});
