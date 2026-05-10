import { useSidePanel } from "../contexts/SidePanelContext";

export function SidePanel() {
  const { open, content, closePanel } = useSidePanel();

  return (
    <>
      {open && (
        <div
          aria-hidden
          className="fixed inset-0 bg-black/10 z-30"
          onClick={closePanel}
        />
      )}
      <aside
        role="complementary"
        aria-label="Detail panel"
        className={`fixed top-0 right-0 h-full w-[480px] max-w-[100vw] bg-surface border-l border-border z-40 transform transition-transform duration-200 ease-out ${open ? "translate-x-0" : "translate-x-full"}`}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <span className="text-sm font-semibold text-ink">Детали</span>
          <button
            type="button"
            onClick={closePanel}
            aria-label="Close panel"
            className="text-muted hover:text-ink text-lg leading-none"
          >
            ×
          </button>
        </div>
        <div className="overflow-y-auto h-[calc(100%-49px)] p-5">{content}</div>
      </aside>
    </>
  );
}
