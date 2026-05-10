import type { ReactNode } from "react";

export type MessageRole = "user" | "agent" | "error";

interface MessageBubbleProps {
  role: MessageRole;
  text: string;
  children?: ReactNode;
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
      <div className="max-w-[80%] bg-accent text-white rounded-card px-4 py-2 text-sm whitespace-pre-wrap">
        {text}
        {children}
      </div>
    </div>
  );
}
