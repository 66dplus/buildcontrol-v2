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
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="flex h-screen bg-bg text-ink">
      {/* Mobile nav drawer overlay */}
      {mobileNavOpen && (
        <button
          type="button"
          aria-label="Закрыть меню"
          className="md:hidden fixed inset-0 bg-black/30 z-30"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <aside
        className={`fixed md:static z-40 h-screen md:h-auto w-[240px] md:w-[220px] flex-shrink-0 bg-bg border-r border-border flex flex-col transition-transform duration-200 ${
          mobileNavOpen ? "translate-x-0" : "-translate-x-full"
        } md:translate-x-0`}
      >
        <div className="px-5 py-5 flex items-center justify-between">
          <span className="font-heading text-lg font-semibold tracking-tight">
            BuildControl
          </span>
          <button
            type="button"
            aria-label="Закрыть меню"
            onClick={() => setMobileNavOpen(false)}
            className="md:hidden text-muted text-xl min-h-11 min-w-11"
          >
            ✕
          </button>
        </div>

        <nav className="flex-1 px-2 space-y-0.5">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={() => setMobileNavOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 min-h-11 rounded-input text-sm transition-colors ${
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
            onClick={() => {
              setMobileNavOpen(false);
              setQuickAskOpen(true);
            }}
            className="w-full flex items-center gap-3 px-3 py-2 min-h-11 rounded-pill bg-accent text-white text-sm font-medium hover:opacity-90"
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

      <main className="flex-1 overflow-y-auto relative w-full md:w-auto">
        {/* Mobile top bar */}
        <div className="md:hidden flex items-center justify-between border-b border-border bg-bg px-4 py-3 sticky top-0 z-20">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Открыть меню"
            className="text-ink text-xl min-h-11 min-w-11"
          >
            ☰
          </button>
          <span className="font-heading text-base font-semibold">BuildControl</span>
          <button
            type="button"
            onClick={() => setQuickAskOpen(true)}
            aria-label="Quick Ask"
            className="text-accent text-xl min-h-11 min-w-11"
          >
            ✦
          </button>
        </div>
        <div className="px-4 md:px-8 py-4 md:py-6">{children}</div>
      </main>

      <SidePanel />
      <QuickAskModal open={quickAskOpen} onClose={() => setQuickAskOpen(false)} />
    </div>
  );
}
