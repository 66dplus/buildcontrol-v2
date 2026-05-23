import type { ReactNode } from "react";

export type MessageRole = "user" | "agent" | "error";

interface MessageBubbleProps {
  role: MessageRole;
  text: string;
  children?: ReactNode;
}

function renderInline(text: string): ReactNode {
  // Handle **bold** and *italic*
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={i}>{part.slice(1, -1)}</em>;
    }
    return <span key={i}>{part}</span>;
  });
}

function renderMarkdown(text: string): ReactNode {
  // Normalise: convert <b>...</b> to **...**
  const normalised = text
    .replace(/<b>(.*?)<\/b>/gi, "**$1**")
    .replace(/<strong>(.*?)<\/strong>/gi, "**$1**")
    .replace(/<br\s*\/?>/gi, "\n");

  const lines = normalised.split("\n");
  const nodes: ReactNode[] = [];
  let listItems: ReactNode[] = [];
  let listType: "ol" | "ul" | null = null;

  function flushList() {
    if (listItems.length === 0) return;
    if (listType === "ol") {
      nodes.push(<ol key={nodes.length} className="list-decimal ml-4 space-y-0.5">{listItems}</ol>);
    } else {
      nodes.push(<ul key={nodes.length} className="list-disc ml-4 space-y-0.5">{listItems}</ul>);
    }
    listItems = [];
    listType = null;
  }

  lines.forEach((line, i) => {
    const numberedMatch = line.match(/^(\d+)\.\s+(.*)/);
    const bulletMatch = line.match(/^[-*]\s+(.*)/);

    if (numberedMatch) {
      if (listType !== "ol") { flushList(); listType = "ol"; }
      listItems.push(<li key={i}>{renderInline(numberedMatch[2])}</li>);
    } else if (bulletMatch) {
      if (listType !== "ul") { flushList(); listType = "ul"; }
      listItems.push(<li key={i}>{renderInline(bulletMatch[1])}</li>);
    } else {
      flushList();
      if (line.trim() === "") {
        nodes.push(<div key={i} className="h-2" />);
      } else {
        nodes.push(<div key={i}>{renderInline(line)}</div>);
      }
    }
  });
  flushList();
  return nodes;
}

export function MessageBubble({ role, text, children }: MessageBubbleProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end" data-testid="message-user">
        <div className="max-w-[80%] bg-bg border border-border text-ink rounded-card px-4 py-2 text-sm whitespace-pre-wrap">
          {text}
        </div>
      </div>
    );
  }
  if (role === "error") {
    return (
      <div className="flex justify-start" data-testid="message-error">
        <div className="max-w-[80%] bg-warning/10 border border-warning text-warning rounded-card px-4 py-2 text-sm whitespace-pre-wrap">
          {text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex justify-start" data-testid="message-agent">
      <div className="max-w-[80%] bg-accent text-white rounded-card px-4 py-2 text-sm leading-relaxed">
        {renderMarkdown(text)}
        {children}
      </div>
    </div>
  );
}
