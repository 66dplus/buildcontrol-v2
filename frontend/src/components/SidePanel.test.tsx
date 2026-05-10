import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SidePanel } from "./SidePanel";
import { SidePanelProvider, useSidePanel } from "../contexts/SidePanelContext";

function Opener() {
  const { openPanel } = useSidePanel();
  return (
    <button onClick={() => openPanel(<div>panel-content</div>)}>open</button>
  );
}

describe("SidePanel", () => {
  it("is hidden when closed", () => {
    render(
      <SidePanelProvider>
        <SidePanel />
      </SidePanelProvider>,
    );
    const panel = screen.getByRole("complementary", { name: /Detail panel/i });
    expect(panel.className).toMatch(/translate-x-full/);
  });

  it("shows content when opened, closes via × button", async () => {
    const user = userEvent.setup();
    render(
      <SidePanelProvider>
        <Opener />
        <SidePanel />
      </SidePanelProvider>,
    );
    await user.click(screen.getByText("open"));
    expect(screen.getByText("panel-content")).toBeInTheDocument();
    await user.click(screen.getByLabelText(/close panel/i));
    expect(
      screen.getByRole("complementary", { name: /Detail panel/i }).className,
    ).toMatch(/translate-x-full/);
  });
});
