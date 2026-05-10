import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageBubble } from "./MessageBubble";

describe("MessageBubble", () => {
  it("renders a user bubble right-aligned", () => {
    render(<MessageBubble role="user" text="Hi there" />);
    const bubble = screen.getByTestId("message-user");
    expect(bubble).toHaveTextContent("Hi there");
    expect(bubble.className).toContain("justify-end");
  });

  it("renders an agent bubble left-aligned with accent background", () => {
    render(<MessageBubble role="agent" text="Hello" />);
    const bubble = screen.getByTestId("message-agent");
    expect(bubble).toHaveTextContent("Hello");
    expect(bubble.className).toContain("justify-start");
    expect(bubble.querySelector(".bg-accent")).toBeTruthy();
  });

  it("renders an error bubble with warning styling", () => {
    render(<MessageBubble role="error" text="Что-то пошло не так" />);
    const bubble = screen.getByTestId("message-error");
    expect(bubble).toHaveTextContent("Что-то пошло не так");
    expect(bubble.querySelector(".text-warning")).toBeTruthy();
  });

  it("renders extra children inside an agent bubble (e.g. ConfirmActionCard)", () => {
    render(
      <MessageBubble role="agent" text="Я предлагаю...">
        <span data-testid="extra-slot">payload</span>
      </MessageBubble>,
    );
    expect(screen.getByTestId("extra-slot")).toBeInTheDocument();
  });
});
