import { useEffect } from "react";
import { ChatPanel } from "./ChatPanel";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function QuickAskModal({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Quick Ask"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="bg-surface rounded-card-lg shadow-card w-[640px] max-w-[92vw] h-[480px] overflow-hidden border border-border flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-border flex items-center justify-between">
          <span className="font-heading text-base">✦ Quick Ask</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-muted hover:text-ink text-lg leading-none"
          >
            ×
          </button>
        </div>
        <div className="flex-1 overflow-hidden">
          <ChatPanel
            greeting="Быстрый вопрос — без покидания текущего экрана."
            placeholder="Спросите про этот проект…"
          />
        </div>
      </div>
    </div>
  );
}
