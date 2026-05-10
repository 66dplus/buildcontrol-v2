import type { ReactNode } from "react";

export interface KpiTileProps {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "warning" | "success";
  icon?: ReactNode;
}

const toneClass: Record<NonNullable<KpiTileProps["tone"]>, string> = {
  neutral: "text-ink",
  warning: "text-warning",
  success: "text-success",
};

export function KpiTile({ label, value, hint, tone = "neutral", icon }: KpiTileProps) {
  return (
    <div
      className="bg-surface border border-border rounded-card p-5 shadow-card flex flex-col gap-2"
      data-testid="kpi-tile"
    >
      <div className="flex items-center justify-between text-muted text-sm font-medium">
        <span>{label}</span>
        {icon ? <span className="opacity-60">{icon}</span> : null}
      </div>
      <div className={`text-kpi tabular ${toneClass[tone]}`}>{value}</div>
      {hint ? <div className="text-xs text-muted">{hint}</div> : null}
    </div>
  );
}
