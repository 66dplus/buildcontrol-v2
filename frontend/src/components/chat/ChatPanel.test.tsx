import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPanel } from "./ChatPanel";
import type { PendingAction } from "../../lib/sse";

interface CapturedHandlers {
  onChunk: (text: string) => void;
  onAction?: (action: PendingAction) => void;
  onDone?: () => void;
  onError?: (msg: string) => void;
}
let captured: CapturedHandlers | null = null;

vi.mock("../../lib/sse", () => ({
  streamChat: vi.fn((_msg: string, handlers: CapturedHandlers) => {
    captured = handlers;
    return new AbortController();
  }),
}));

beforeEach(() => {
  captured = null;
  vi.clearAllMocks();
});

const FAKE_ACTION: PendingAction = {
  action_id: "test-uuid",
  display: {
    title: "Создать задачу: «Тест»",
    fields: [
      { label: "Название", value: "Тест" },
      { label: "Ответственный (ID)", value: "5" },
    ],
  },
};

describe("ChatPanel", () => {
  it("shows the greeting before any messages are sent", () => {
    render(<ChatPanel greeting="Привет!" />);
    expect(screen.getByTestId("chat-greeting")).toHaveTextContent("Привет!");
  });

  it("appends a user bubble + empty agent bubble on send", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.type(screen.getByTestId("chat-input"), "тест");
    await user.click(screen.getByTestId("chat-send"));
    expect(screen.getByTestId("message-user")).toHaveTextContent("тест");
    expect(screen.getByTestId("message-agent")).toBeInTheDocument();
  });

  it("appends streamed chunks to the agent bubble", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.type(screen.getByTestId("chat-input"), "ping");
    await user.click(screen.getByTestId("chat-send"));
    captured?.onChunk("Hello ");
    captured?.onChunk("мир");
    captured?.onDone?.();
    expect(await screen.findByText("Hello мир")).toBeInTheDocument();
  });

  it("sends on Enter (without shift)", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.type(screen.getByTestId("chat-input"), "go{enter}");
    expect(screen.getByTestId("message-user")).toHaveTextContent("go");
  });

  it("does NOT send when input is empty whitespace", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.type(screen.getByTestId("chat-input"), "   ");
    await user.click(screen.getByTestId("chat-send"));
    expect(screen.queryByTestId("message-user")).not.toBeInTheDocument();
  });

  it("disables input + button while streaming and re-enables on done", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.type(screen.getByTestId("chat-input"), "ping");
    await user.click(screen.getByTestId("chat-send"));
    expect(screen.getByTestId("chat-input")).toBeDisabled();
    expect(screen.getByTestId("chat-send")).toBeDisabled();
    captured?.onDone?.();
    expect(await screen.findByTestId("chat-input")).not.toBeDisabled();
  });

  it("renders an error bubble and stops streaming on onError", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.type(screen.getByTestId("chat-input"), "ping");
    await user.click(screen.getByTestId("chat-send"));
    captured?.onError?.("сервер упал");
    expect(await screen.findByTestId("message-error")).toHaveTextContent("сервер упал");
  });

  it("shows ConfirmActionCard when onAction is called", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.type(screen.getByTestId("chat-input"), "создай задачу");
    await user.click(screen.getByTestId("chat-send"));

    captured?.onAction?.(FAKE_ACTION);

    expect(await screen.findByTestId("confirm-action-card")).toBeInTheDocument();
    expect(screen.getByText("Создать задачу: «Тест»")).toBeInTheDocument();
  });

  it("removes ConfirmActionCard on cancel", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.type(screen.getByTestId("chat-input"), "создай задачу");
    await user.click(screen.getByTestId("chat-send"));
    captured?.onAction?.(FAKE_ACTION);
    await screen.findByTestId("confirm-action-card");

    await user.click(screen.getByTestId("cancel-btn"));
    expect(screen.queryByTestId("confirm-action-card")).not.toBeInTheDocument();
  });

  it("calls /api/agent/confirm on Confirm click and shows success", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ok: true, result: {} }),
      }),
    );

    render(<ChatPanel />);
    await user.type(screen.getByTestId("chat-input"), "создай задачу");
    await user.click(screen.getByTestId("chat-send"));
    captured?.onAction?.(FAKE_ACTION);
    await screen.findByTestId("confirm-action-card");

    await user.click(screen.getByTestId("confirm-btn"));

    expect(fetch).toHaveBeenCalledWith(
      "/api/agent/confirm",
      expect.objectContaining({ method: "POST" }),
    );
    expect(await screen.findByText("Действие выполнено успешно.")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
