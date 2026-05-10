import { useEffect, useRef, useState } from "react";
import { streamChat } from "../../lib/sse";
import { MessageBubble, type MessageRole } from "./MessageBubble";

interface ChatMessage {
  id: number;
  role: MessageRole;
  text: string;
}

interface ChatPanelProps {
  /** Greeting shown before the first user message. */
  greeting?: string;
  /** Maximum height for the message list (Tailwind class). Empty = grow. */
  scrollMaxHeight?: string;
  /** Placeholder for the input box. */
  placeholder?: string;
}

export function ChatPanel({
  greeting = "Спросите что-нибудь о ваших проектах.",
  scrollMaxHeight = "",
  placeholder = "Например: какие проекты в перерасходе?",
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const ctrlRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const idRef = useRef(0);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => () => ctrlRef.current?.abort(), []);

  function nextId() {
    idRef.current += 1;
    return idRef.current;
  }

  function send() {
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg: ChatMessage = { id: nextId(), role: "user", text };
    const agentMsg: ChatMessage = { id: nextId(), role: "agent", text: "" };
    const agentId = agentMsg.id;
    setMessages((prev) => [...prev, userMsg, agentMsg]);
    setInput("");
    setStreaming(true);

    ctrlRef.current = streamChat(text, {
      onChunk: (chunk) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === agentId ? { ...m, text: m.text + chunk } : m)),
        );
      },
      onDone: () => setStreaming(false),
      onError: (msg) => {
        setMessages((prev) => {
          const filtered = prev.filter((m) => m.id !== agentId);
          return [...filtered, { id: nextId(), role: "error", text: msg }];
        });
        setStreaming(false);
      },
    });
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="flex flex-col h-full bg-surface" data-testid="chat-panel">
      <div
        ref={scrollRef}
        className={`flex-1 overflow-y-auto p-4 flex flex-col gap-3 ${scrollMaxHeight}`}
        data-testid="chat-messages"
      >
        {messages.length === 0 ? (
          <div className="text-muted text-sm text-center py-6" data-testid="chat-greeting">
            {greeting}
          </div>
        ) : (
          messages.map((m) => <MessageBubble key={m.id} role={m.role} text={m.text} />)
        )}
        {streaming && messages[messages.length - 1]?.text === "" ? (
          <div className="text-muted text-xs" data-testid="chat-thinking">
            …думаю
          </div>
        ) : null}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="border-t border-border p-3 flex items-end gap-2 bg-surface"
        data-testid="chat-form"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder={placeholder}
          disabled={streaming}
          rows={1}
          data-testid="chat-input"
          className="flex-1 resize-none rounded-pill border border-border bg-bg text-ink text-sm px-4 py-2 focus:outline-none focus:border-accent disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          data-testid="chat-send"
          className="bg-accent text-white text-sm font-medium rounded-pill px-4 py-2 hover:bg-accent/90 disabled:opacity-50"
        >
          {streaming ? "…" : "Отправить"}
        </button>
      </form>
    </div>
  );
}
