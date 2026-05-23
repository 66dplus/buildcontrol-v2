import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquipmentTab } from "./EquipmentTab";
import type { EquipmentRow } from "../../../lib/api";

function row(overrides: Partial<EquipmentRow> = {}): EquipmentRow {
  return {
    id: 1,
    project_id: 7,
    phase: "Каркас",
    task_name: "Бетонирование",
    equipment_name: "Бетононасос",
    price_per_hour: 2_500,
    hours_plan: 40,
    total_plan: 100_000,
    hours_actual: 42,
    total_actual: 105_000,
    ...overrides,
  };
}

describe("EquipmentTab", () => {
  it("renders empty state when no rows", () => {
    render(<EquipmentTab rows={[]} projectId={7} tasks={[]} onAdded={() => {}} />);
    expect(screen.getByTestId("equipment-empty")).toBeInTheDocument();
  });

  it("renders one row per equipment item", () => {
    render(
      <EquipmentTab
        rows={[row({ id: 1 }), row({ id: 2, equipment_name: "Кран" })]}
        projectId={7}
        tasks={[]}
        onAdded={() => {}}
      />,
    );
    expect(screen.getByTestId("equipment-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("equipment-row-2")).toBeInTheDocument();
    expect(screen.getByText("Кран")).toBeInTheDocument();
  });

  it("highlights overrun rows when total variance > 15%", () => {
    render(
      <EquipmentTab
        rows={[
          row({ id: 1, total_plan: 100, total_actual: 105 }),
          row({ id: 2, total_plan: 100, total_actual: 200 }),
        ]}
        projectId={7}
        tasks={[]}
        onAdded={() => {}}
      />,
    );
    expect(screen.getByTestId("equipment-row-1").className).not.toContain("bg-warning");
    expect(screen.getByTestId("equipment-row-2").className).toContain("bg-warning");
  });
});
