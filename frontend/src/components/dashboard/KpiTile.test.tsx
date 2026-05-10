import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiTile } from "./KpiTile";

describe("KpiTile", () => {
  it("renders label and value", () => {
    render(<KpiTile label="Бюджет план" value="82M ₽" />);
    expect(screen.getByText("Бюджет план")).toBeInTheDocument();
    expect(screen.getByText("82M ₽")).toBeInTheDocument();
  });

  it("renders the optional hint when provided", () => {
    render(<KpiTile label="Бюджет план" value="82M ₽" hint="за всё время" />);
    expect(screen.getByText("за всё время")).toBeInTheDocument();
  });

  it("applies the warning tone class to the value when tone='warning'", () => {
    render(<KpiTile label="Аномалии" value="3" tone="warning" />);
    expect(screen.getByText("3")).toHaveClass("text-warning");
  });

  it("applies the success tone class when tone='success'", () => {
    render(<KpiTile label="В норме" value="12" tone="success" />);
    expect(screen.getByText("12")).toHaveClass("text-success");
  });

  it("uses the neutral ink colour by default", () => {
    render(<KpiTile label="Активные" value="5" />);
    expect(screen.getByText("5")).toHaveClass("text-ink");
  });

  it("renders an icon when given", () => {
    render(
      <KpiTile
        label="Иконка"
        value="—"
        icon={<span data-testid="icon-slot">★</span>}
      />,
    );
    expect(screen.getByTestId("icon-slot")).toBeInTheDocument();
  });
});
