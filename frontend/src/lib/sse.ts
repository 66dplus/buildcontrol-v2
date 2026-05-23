/**
 * SSE parser for streaming chat responses from POST /api/agent/chat.
 *
 * EventSource doesn't support POST; we use fetch + ReadableStream and parse
 * the `event: <name>\ndata: <json>\n\n` framing ourselves.
 */

export interface SseEvent {
  event: string;
  data: unknown;
}

export interface PendingAction {
  action_id: string;
  display: {
    title: string;
    fields: Array<{ label: string; value: string }>;
  };
}

export interface ChatStreamHandlers {
  onChunk: (text: string) => void;
  onAction?: (action: PendingAction) => void;
  onDone?: () => void;
  onError?: (message: string) => void;
}

function readBearerToken(): string {
  if (typeof document === "undefined") return "";
  const meta = document.querySelector('meta[name="api-token"]') as HTMLMetaElement | null;
  return meta?.content?.trim() ?? "";
}

function parseEvents(buffer: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = [];
  let rest = buffer;
  while (true) {
    const sep = rest.indexOf("\n\n");
    if (sep === -1) break;
    const block = rest.slice(0, sep);
    rest = rest.slice(sep + 2);
    let event = "message";
    let dataLine = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7);
      else if (line.startsWith("data: ")) dataLine += line.slice(6);
    }
    let data: unknown = null;
    if (dataLine) {
      try {
        data = JSON.parse(dataLine);
      } catch {
        data = dataLine;
      }
    }
    events.push({ event, data });
  }
  return { events, rest };
}

/**
 * Send a chat message and stream the agent's response.
 * Returns an AbortController so callers can cancel mid-stream.
 */
export function streamChat(
  message: string,
  handlers: ChatStreamHandlers,
  opts?: { signal?: AbortSignal },
): AbortController {
  const ctrl = new AbortController();
  const signal = opts?.signal
    ? mergeSignals(opts.signal, ctrl.signal)
    : ctrl.signal;

  (async () => {
    const token = readBearerToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    let res: Response;
    try {
      res = await fetch("/api/agent/chat", {
        method: "POST",
        headers,
        body: JSON.stringify({ message }),
        signal,
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        handlers.onError?.((err as Error).message);
      }
      return;
    }

    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => "");
      handlers.onError?.(text || `HTTP ${res.status}`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { events, rest } = parseEvents(buffer);
        buffer = rest;
        for (const ev of events) {
          if (ev.event === "chunk") {
            const d = ev.data as { text?: string; content?: string };
            const t = d?.content ?? d?.text;
            if (typeof t === "string") handlers.onChunk(t);
          } else if (ev.event === "action") {
            handlers.onAction?.(ev.data as PendingAction);
          } else if (ev.event === "done") {
            handlers.onDone?.();
            return;
          } else if (ev.event === "error") {
            const d = ev.data as { message?: string; content?: string };
            handlers.onError?.(d?.content ?? d?.message ?? "stream error");
            return;
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        handlers.onError?.((err as Error).message);
      }
    }
  })();

  return ctrl;
}

function mergeSignals(a: AbortSignal, b: AbortSignal): AbortSignal {
  if (a.aborted) return a;
  if (b.aborted) return b;
  const ctrl = new AbortController();
  a.addEventListener("abort", () => ctrl.abort());
  b.addEventListener("abort", () => ctrl.abort());
  return ctrl.signal;
}

// Exported for unit testing.
export { parseEvents };
