import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

interface SidePanelContextValue {
  open: boolean;
  content: ReactNode | null;
  openPanel: (content: ReactNode) => void;
  closePanel: () => void;
}

const SidePanelContext = createContext<SidePanelContextValue>({
  open: false,
  content: null,
  openPanel: () => {},
  closePanel: () => {},
});

export function SidePanelProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<ReactNode | null>(null);

  const openPanel = useCallback((node: ReactNode) => {
    setContent(node);
    setOpen(true);
  }, []);

  const closePanel = useCallback(() => {
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePanel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, closePanel]);

  return (
    <SidePanelContext.Provider value={{ open, content, openPanel, closePanel }}>
      {children}
    </SidePanelContext.Provider>
  );
}

export function useSidePanel() {
  return useContext(SidePanelContext);
}
