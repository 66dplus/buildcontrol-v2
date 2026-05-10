import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TabBar, PROJECT_TABS } from "./TabBar";

describe("TabBar", () => {
  it("renders all five tabs", () => {
    render(<TabBar active="overview" onChange={() => {}} />);
    PROJECT_TABS.forEach((t) => {
      expect(screen.getByTestId(`tab-${t.key}`)).toBeInTheDocument();
    });
  });

  it("marks the active tab with aria-selected=true", () => {
    render(<TabBar active="materials" onChange={() => {}} />);
    expect(screen.getByTestId("tab-materials")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("tab-overview")).toHaveAttribute("aria-selected", "false");
  });

  it("calls onChange with the clicked tab key", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TabBar active="overview" onChange={onChange} />);
    await user.click(screen.getByTestId("tab-stages"));
    expect(onChange).toHaveBeenCalledWith("stages");
  });
});
