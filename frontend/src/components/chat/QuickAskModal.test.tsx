import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuickAskModal } from "./QuickAskModal";

describe("QuickAskModal", () => {
  it("does not render when closed", () => {
    render(<QuickAskModal open={false} onClose={() => {}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders when open", () => {
    render(<QuickAskModal open onClose={() => {}} />);
    expect(screen.getByRole("dialog", { name: /Quick Ask/i })).toBeInTheDocument();
  });

  it("calls onClose on backdrop click", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<QuickAskModal open onClose={onClose} />);
    await user.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose on Escape", () => {
    const onClose = vi.fn();
    render(<QuickAskModal open onClose={onClose} />);
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(onClose).toHaveBeenCalled();
  });
});
