import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { api, ApiError } from "./api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api.whoami", () => {
  it("calls GET /api/whoami and returns parsed body", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        user: "director",
        role: "director",
        host: "standalone",
        capabilities: ["chat"],
      }),
    );
    const result = await api.whoami();
    expect(fetchMock).toHaveBeenCalledWith("/api/whoami", expect.any(Object));
    expect(result.host).toBe("standalone");
  });

  it("throws ApiError on non-2xx", async () => {
    fetchMock.mockResolvedValueOnce(new Response("nope", { status: 500 }));
    await expect(api.whoami()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("api.phases", () => {
  it("hits /api/projects/{id}/phases", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    await api.phases(42);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/projects/42/phases");
  });
});

describe("api.materials", () => {
  it("appends phase + task as query string when supplied", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    await api.materials(7, "Каркас", "Стены");
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/projects/7/materials-all");
    expect(url).toContain("phase=%D0%9A%D0%B0%D1%80%D0%BA%D0%B0%D1%81");
    expect(url).toContain("task=%D0%A1%D1%82%D0%B5%D0%BD%D1%8B");
  });

  it("omits filters when not provided", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    await api.materials(7);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/projects/7/materials-all");
  });
});

describe("api.decideRequest", () => {
  it("sends POST with FormData to the decide endpoint", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));
    await api.decideRequest(123, "approve", "ok");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/purchase-requests/123/decide");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });
});
