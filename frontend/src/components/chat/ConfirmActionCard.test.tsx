import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmActionCard } from "./ConfirmActionCard";

describe("ConfirmActionCard", () => {
  it("renders the title and all field rows", () => {
    render(
      <ConfirmActionCard
        title="Создать задачу"
        fields={[
          { label: "Назначен", value: "Алексей" },
          { label: "Проект", value: "ТЦ Северный" },
        ]}
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByTestId("confirm-action-card")).toBeInTheDocument();
    expect(screen.getByText("Создать задачу")).toBeInTheDocument();
    expect(screen.getByText("Алексей")).toBeInTheDocument();
    expect(screen.getByText("ТЦ Северный")).toBeInTheDocument();
  });

  it("calls onConfirm when the confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmActionCard title="X" fields={[]} onConfirm={onConfirm} onCancel={() => {}} />,
    );
    await user.click(screen.getByTestId("confirm-btn"));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("calls onCancel when the cancel button is clicked", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmActionCard title="X" fields={[]} onConfirm={() => {}} onCancel={onCancel} />,
    );
    await user.click(screen.getByTestId("cancel-btn"));
    expect(onCancel).toHaveBeenCalled();
  });

  it("disables both buttons and shows 'Выполняется…' when busy", () => {
    render(
      <ConfirmActionCard
        title="X" fields={[]} onConfirm={() => {}} onCancel={() => {}} busy
      />,
    );
    expect(screen.getByTestId("confirm-btn")).toBeDisabled();
    expect(screen.getByTestId("cancel-btn")).toBeDisabled();
    expect(screen.getByText("Выполняется…")).toBeInTheDocument();
  });
});
