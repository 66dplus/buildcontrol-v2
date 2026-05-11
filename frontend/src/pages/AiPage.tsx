import { useLocation } from "react-router-dom";
import { ChatPanel } from "../components/chat/ChatPanel";

export function AiPage() {
  const { state } = useLocation() as { state?: { autoMessage?: string } };
  const autoMessage = state?.autoMessage;
  return (
    <div className="flex flex-col h-[calc(100vh-3rem)]" data-testid="ai-page">
      <div className="mb-4">
        <h1 className="font-heading text-lg md:text-2xl text-ink">AI Assistant</h1>
        <p className="text-muted text-sm">
          Аналитика по проектам, задачам и закупкам — задавайте вопросы естественным языком.
        </p>
      </div>
      <div className="flex-1 border border-border rounded-card-lg overflow-hidden shadow-card">
        <ChatPanel initialMessage={autoMessage} autoSend={!!autoMessage} />
      </div>
    </div>
  );
}
