import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MaterialsTab } from "./MaterialsTab";
import { SidePanelProvider } from "../../../contexts/SidePanelContext";
import { SidePanel } from "../../SidePanel";
import type { MaterialRow } from "../../../lib/api";

function material(overrides: Partial<MaterialRow> = {}): MaterialRow {
  return {
    id: 1,
    project_id: 7,
    phase: "Каркас",
    task_name: "Армирование",
    material_name: "Арматура А500С",
    unit: "т",
    price_plan: 80_000,
    qty_plan: 10,
    cost_plan: 800_000,
    price_actual: 82_000,
    qty_bought: 10,
    qty_consumed: 8,
    qty_stock: 2,
    cost_actual: 820_000,
    ...overrides,
  };
}

function renderTab(materials: MaterialRow[]) {
  return render(
    <SidePanelProvider>
      <MaterialsTab
        materials={materials}
        projectId={7}
        tasks={[]}
        onAdded={() => {}}
      />
      <SidePanel />
    </SidePanelProvider>,
  );
}

describe("MaterialsTab", () => {
  it("renders empty state when no materials", () => {
    renderTab([]);
    expect(screen.getByTestId("materials-empty")).toBeInTheDocument();
  });

  it("renders one row per material", () => {
    renderTab([
      material({ id: 1, material_name: "Арматура" }),
      material({ id: 2, material_name: "Цемент", phase: "Каркас", task_name: "Бетонирование" }),
    ]);
    expect(screen.getByTestId("material-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("material-row-2")).toBeInTheDocument();
    expect(screen.getByText("Арматура")).toBeInTheDocument();
    expect(screen.getByText("Цемент")).toBeInTheDocument();
  });

  it("highlights rows where actual price > plan price * 1.05", () => {
    renderTab([
      material({ id: 1, price_plan: 100, price_actual: 104 }), // within tolerance
      material({ id: 2, price_plan: 100, price_actual: 110 }), // overpriced
    ]);
    expect(screen.getByTestId("material-row-1").className).not.toContain("bg-warning");
    expect(screen.getByTestId("material-row-2").className).toContain("bg-warning");
  });

  it("clicking a row opens MaterialDetailPanel in side panel", async () => {
    const user = userEvent.setup();
    renderTab([material({ id: 42, material_name: "Гипс" })]);
    await user.click(screen.getByTestId("material-row-42"));
    const panel = screen.getByTestId("material-detail-panel");
    expect(panel).toBeInTheDocument();
    // Material name appears both in the row and the panel — scope to the panel.
    expect(panel).toHaveTextContent("Гипс");
  });
});
