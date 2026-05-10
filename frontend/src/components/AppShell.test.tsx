import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";
import { AuthProvider } from "../contexts/AuthContext";
import { SidePanelProvider } from "../contexts/SidePanelContext";

function whoamiResponse() {
  return new Response(
    JSON.stringify({
      user: "director",
      role: "director",
      host: "standalone",
      capabilities: [],
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

beforeEach(() => {
  globalThis.fetch = vi.fn().mockImplementation(async () => whoamiResponse()) as unknown as typeof fetch;
});

function renderShell(initial = "/") {
  return render(
    <AuthProvider>
      <SidePanelProvider>
        <MemoryRouter initialEntries={[initial]}>
          <AppShell>
            <Routes>
              <Route path="/" element={<div>home</div>} />
              <Route path="/ai" element={<div>ai-page</div>} />
            </Routes>
          </AppShell>
        </MemoryRouter>
      </SidePanelProvider>
    </AuthProvider>,
  );
}

describe("AppShell", () => {
  it("renders the brand and navigation links", async () => {
    renderShell();
    expect(screen.getByText("BuildControl")).toBeInTheDocument();
    expect(screen.getByText("Дашборд")).toBeInTheDocument();
    expect(screen.getByText("AI Assistant")).toBeInTheDocument();
    expect(screen.getByText("Quick Ask")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/director · standalone/)).toBeInTheDocument(),
    );
  });

  it("renders child route content in main", () => {
    renderShell("/");
    expect(screen.getByText("home")).toBeInTheDocument();
  });

  it("opens Quick Ask modal when button clicked", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByText("Quick Ask"));
    expect(screen.getByRole("dialog", { name: /Quick Ask/i })).toBeInTheDocument();
  });
});
