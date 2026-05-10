import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SidePanelProvider, useSidePanel } from "./SidePanelContext";

function Harness() {
  const { open, content, openPanel, closePanel } = useSidePanel();
  return (
    <div>
      <button onClick={() => openPanel(<div>panel-body</div>)}>open</button>
      <button onClick={closePanel}>close</button>
      <span data-testid="state">{open ? "open" : "closed"}</span>
      {open && <div data-testid="content">{content}</div>}
    </div>
  );
}

describe("SidePanelContext", () => {
  it("opens panel with content", async () => {
    const user = userEvent.setup();
    render(
      <SidePanelProvider>
        <Harness />
      </SidePanelProvider>,
    );
    expect(screen.getByTestId("state").textContent).toBe("closed");
    await user.click(screen.getByText("open"));
    expect(screen.getByTestId("state").textContent).toBe("open");
    expect(screen.getByText("panel-body")).toBeInTheDocument();
  });

  it("closes via close()", async () => {
    const user = userEvent.setup();
    render(
      <SidePanelProvider>
        <Harness />
      </SidePanelProvider>,
    );
    await user.click(screen.getByText("open"));
    await user.click(screen.getByText("close"));
    expect(screen.getByTestId("state").textContent).toBe("closed");
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(
      <SidePanelProvider>
        <Harness />
      </SidePanelProvider>,
    );
    await user.click(screen.getByText("open"));
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(screen.getByTestId("state").textContent).toBe("closed");
  });
});
