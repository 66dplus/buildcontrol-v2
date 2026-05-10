import { describe, it, expect, beforeEach, vi } from "vitest";
import { parseEvents, streamChat } from "./sse";

describe("parseEvents", () => {
  it("returns no events when buffer has no full block", () => {
    const r = parseEvents("event: chunk\ndata: ");
    expect(r.events).toHaveLength(0);
    expect(r.rest).toBe("event: chunk\ndata: ");
  });

  it("parses a single complete event with JSON data", () => {
    const r = parseEvents("event: chunk\ndata: {\"text\":\"hi\"}\n\n");
    expect(r.events).toEqual([{ event: "chunk", data: { text: "hi" } }]);
    expect(r.rest).toBe("");
  });

  it("parses multiple events back-to-back", () => {
    const buf =
      "event: chunk\ndata: {\"text\":\"A\"}\n\n" +
      "event: chunk\ndata: {\"text\":\"B\"}\n\n" +
      "event: done\ndata: {}\n\n";
    const r = parseEvents(buf);
    expect(r.events.map((e) => e.event)).toEqual(["chunk", "chunk", "done"]);
    expect(r.rest).toBe("");
  });

  it("keeps an incomplete trailing event in rest", () => {
    const buf =
      "event: chunk\ndata: {\"text\":\"A\"}\n\n" +
      "event: chunk\ndata: ";
    const r = parseEvents(buf);
    expect(r.events).toHaveLength(1);
    expect(r.rest).toBe("event: chunk\ndata: ");
  });

  it("falls back to string data when JSON parse fails", () => {
    const r = parseEvents("event: chunk\ndata: not-json\n\n");
    expect(r.events[0].data).toBe("not-json");
  });
});

function makeStreamingResponse(chunks: string[]): Response {
  let i = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(new TextEncoder().encode(chunks[i++]));
      } else {
        controller.close();
      }
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("streamChat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("calls onChunk for each chunk event and onDone at the end", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      makeStreamingResponse([
        "event: chunk\ndata: {\"text\":\"Привет \"}\n\n",
        "event: chunk\ndata: {\"text\":\"мир\"}\n\n",
        "event: done\ndata: {}\n\n",
      ]),
    ) as unknown as typeof fetch;

    const chunks: string[] = [];
    let done = false;
    streamChat("hi", {
      onChunk: (t) => chunks.push(t),
      onDone: () => { done = true; },
    });
    await vi.waitFor(() => expect(done).toBe(true));
    expect(chunks).toEqual(["Привет ", "мир"]);
  });

  it("calls onError when the server returns a non-2xx status", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response("boom", { status: 500 }),
    ) as unknown as typeof fetch;
    let err = "";
    streamChat("hi", {
      onChunk: () => {},
      onError: (m) => { err = m; },
    });
    await vi.waitFor(() => expect(err).toBeTruthy());
    expect(err).toMatch(/boom|500/);
  });

  it("forwards an error event in the stream to onError", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      makeStreamingResponse([
        "event: error\ndata: {\"message\":\"upstream gone\"}\n\n",
      ]),
    ) as unknown as typeof fetch;
    let err = "";
    streamChat("hi", {
      onChunk: () => {},
      onError: (m) => { err = m; },
    });
    await vi.waitFor(() => expect(err).toBeTruthy());
    expect(err).toBe("upstream gone");
  });

  it("passes the message in the POST body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      makeStreamingResponse(["event: done\ndata: {}\n\n"]),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    let done = false;
    streamChat("ping", { onChunk: () => {}, onDone: () => { done = true; } });
    await vi.waitFor(() => expect(done).toBe(true));
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ message: "ping" });
  });
});
