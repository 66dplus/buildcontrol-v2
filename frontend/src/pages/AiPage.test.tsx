import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AiPage } from "./AiPage";

vi.mock("../lib/sse", () => ({
  streamChat: vi.fn(() => new AbortController()),
}));

describe("AiPage", () => {
  it("renders the heading and the chat panel", () => {
    render(<AiPage />);
    expect(screen.getByTestId("ai-page")).toBeInTheDocument();
    expect(screen.getByText("AI Assistant")).toBeInTheDocument();
    expect(screen.getByTestId("chat-panel")).toBeInTheDocument();
  });
});
