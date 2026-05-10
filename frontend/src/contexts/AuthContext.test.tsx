import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext";

function Harness() {
  const { whoami, loading, error } = useAuth();
  return (
    <div>
      <span data-testid="loading">{loading ? "yes" : "no"}</span>
      <span data-testid="user">{whoami?.user ?? ""}</span>
      <span data-testid="host">{whoami?.host ?? ""}</span>
      <span data-testid="error">{error ?? ""}</span>
    </div>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("AuthProvider", () => {
  it("loads whoami on mount", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          user: "director",
          role: "director",
          host: "standalone",
          capabilities: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("no"));
    expect(screen.getByTestId("user").textContent).toBe("director");
    expect(screen.getByTestId("host").textContent).toBe("standalone");
  });

  it("captures error when whoami fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("denied", { status: 401 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("no"));
    expect(screen.getByTestId("error").textContent).toBe("denied");
  });
});
