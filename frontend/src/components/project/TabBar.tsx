export type TabKey = "overview" | "stages" | "materials" | "labor" | "equipment";

export interface TabDef {
  key: TabKey;
  label: string;
}

export const PROJECT_TABS: TabDef[] = [
  { key: "overview", label: "Обзор" },
  { key: "stages", label: "Этапы и задачи" },
  { key: "materials", label: "Материалы" },
  { key: "labor", label: "Трудозатраты" },
  { key: "equipment", label: "Техника" },
];

interface TabBarProps {
  active: TabKey;
  onChange: (key: TabKey) => void;
}

export function TabBar({ active, onChange }: TabBarProps) {
  return (
    <div
      role="tablist"
      aria-label="Project sections"
      className="flex items-center gap-1 border-b border-border bg-surface rounded-card-lg px-2 overflow-x-auto whitespace-nowrap"
      data-testid="tab-bar"
    >
      {PROJECT_TABS.map((t) => {
        const isActive = t.key === active;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            data-testid={`tab-${t.key}`}
            onClick={() => onChange(t.key)}
            className={`px-4 py-3 min-h-11 text-sm font-medium transition-colors -mb-px border-b-2 flex-shrink-0 ${
              isActive
                ? "text-accent border-accent"
                : "text-muted hover:text-ink border-transparent"
            }`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
