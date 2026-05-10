import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ProjectHeader } from "./ProjectHeader";

function renderHeader(
  name: string,
  totals = { total_plan: 30_000_000, total_actual: 31_000_000, variance_pct: 3.3, completion_pct: 50 },
) {
  return render(
    <MemoryRouter>
      <ProjectHeader name={name} totals={totals} />
    </MemoryRouter>,
  );
}

describe("ProjectHeader", () => {
  it("renders the project name and back link to /", () => {
    renderHeader("Торговый центр");
    expect(screen.getByText("Торговый центр")).toBeInTheDocument();
    const back = screen.getByTestId("back-link");
    expect(back.getAttribute("href")).toBe("/");
  });

  it("shows В норме badge when variance ≤ 0", () => {
    renderHeader("Test", {
      total_plan: 100, total_actual: 95, variance_pct: -5, completion_pct: 50,
    });
    expect(screen.getByText("В норме")).toBeInTheDocument();
  });

  it("shows Внимание badge when variance is between 1 and 15", () => {
    renderHeader("Test", {
      total_plan: 100, total_actual: 110, variance_pct: 10, completion_pct: 50,
    });
    expect(screen.getByText("Внимание")).toBeInTheDocument();
  });

  it("shows Перерасход badge when variance > 15", () => {
    renderHeader("Test", {
      total_plan: 100, total_actual: 130, variance_pct: 30, completion_pct: 50,
    });
    expect(screen.getByText("Перерасход")).toBeInTheDocument();
  });

  it("formats plan, actual, variance and completion in the meta row", () => {
    renderHeader("Test", {
      total_plan: 30_000_000,
      total_actual: 31_500_000,
      variance_pct: 5,
      completion_pct: 67,
    });
    expect(screen.getByText("30M ₽")).toBeInTheDocument();
    expect(screen.getByText("31.5M ₽")).toBeInTheDocument();
    expect(screen.getByText("+5.0%")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument();
  });
});
