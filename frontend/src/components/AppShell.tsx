import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { SidePanel } from "./SidePanel";
import { QuickAskModal } from "./chat/QuickAskModal";

interface NavItem {
  to: string;
  label: string;
  icon: string;
}

const NAV: NavItem[] = [
  { to: "/", label: "Дашборд", icon: "▣" },
  { to: "/ai", label: "AI Assistant", icon: "✦" },
  { to: "/foreman-report", label: "Отчёт прораба", icon: "✎" },
  { to: "/procurement", label: "Закупки", icon: "₽" },
  { to: "/upload", label: "Загрузка проекта", icon: "↥" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { whoami, loading } = useAuth();
  const [quickAskOpen, setQuickAskOpen] = useState(false);

  return (
    <div className="flex h-screen bg-bg text-ink">
      <aside className="w-[220px] flex-shrink-0 bg-bg border-r border-border flex flex-col">
        <div className="px-5 py-5">
          <span className="font-heading text-lg font-semibold tracking-tight">
            BuildControl
          </span>
        </div>

        <nav className="flex-1 px-2 space-y-0.5">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-input text-sm transition-colors ${
                  isActive
                    ? "bg-accent-soft text-accent font-semibold"
                    : "text-muted hover:bg-white hover:text-ink"
                }`
              }
            >
              <span className="w-4 text-center text-base">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="px-2 pb-2">
          <button
            type="button"
            onClick={() => setQuickAskOpen(true)}
            className="w-full flex items-center gap-3 px-3 py-2 rounded-pill bg-accent text-white text-sm font-medium hover:opacity-90"
          >
            <span>✦</span>
            <span>Quick Ask</span>
          </button>
        </div>

        <div className="px-5 py-3 border-t border-border text-xs text-muted">
          {loading
            ? "…"
            : whoami
              ? `${whoami.user} · ${whoami.host}`
              : "не авторизован"}
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto relative">
        <div className="px-8 py-6">{children}</div>
      </main>

      <SidePanel />
      <QuickAskModal open={quickAskOpen} onClose={() => setQuickAskOpen(false)} />
    </div>
  );
}
