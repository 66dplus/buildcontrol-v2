import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { DashboardProject } from "../../lib/api";
import { formatMoney, formatPercent, varianceTier, TIER_ROW_BG, TIER_ICON } from "../../lib/format";

type SortKey = "name" | "total_plan" | "total_actual" | "schedule_variance_pct";
type SortDir = "asc" | "desc";

interface ProjectTableProps {
  projects: DashboardProject[];
}

interface VarianceBadge {
  label: string;
  className: string;
}

function classifyVariance(pct: number): VarianceBadge {
  if (pct <= 0) {
    return {
      label: "В норме",
      className: "bg-success/10 text-success border-success/30",
    };
  }
  if (pct <= 15) {
    return {
      label: "Внимание",
      className: "bg-warning/10 text-warning border-warning/30",
    };
  }
  return {
    label: "Перерасход",
    className: "bg-warning text-white border-warning",
  };
}

const HEADERS: { key: SortKey; label: string; align: "left" | "right"; hint?: string }[] = [
  { key: "name", label: "Проект", align: "left" },
  { key: "total_plan", label: "Бюджет план", align: "right" },
  { key: "total_actual", label: "Бюджет факт", align: "right" },
  {
    key: "schedule_variance_pct",
    label: "Отклонение",
    align: "right",
    hint: "Отклонение от плана к сегодняшней дате",
  },
];

export function ProjectTable({ projects }: ProjectTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("schedule_variance_pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const navigate = useNavigate();

  const sorted = useMemo(() => {
    const copy = [...projects];
    copy.sort((a, b) => {
      const av = a[sortKey] as string | number;
      const bv = b[sortKey] as string | number;
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc" ? av.localeCompare(bv, "ru") : bv.localeCompare(av, "ru");
      }
      const an = Number(av);
      const bn = Number(bv);
      return sortDir === "asc" ? an - bn : bn - an;
    });
    return copy;
  }, [projects, sortKey, sortDir]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  }

  if (projects.length === 0) {
    return (
      <div
        className="bg-surface border border-border rounded-card p-8 text-muted text-sm text-center"
        data-testid="project-table-empty"
      >
        Нет проектов в портфеле
      </div>
    );
  }

  return (
    <div
      className="bg-surface border border-border rounded-card overflow-x-auto shadow-card"
      data-testid="project-table"
    >
      <table className="w-full text-sm min-w-[680px]">
        <thead className="bg-bg border-b border-border text-muted text-xs uppercase tracking-wide">
          <tr>
            {HEADERS.map((h) => (
              <th
                key={h.key}
                className={`px-4 py-3 font-medium ${
                  h.align === "right" ? "text-right" : "text-left"
                }`}
                title={h.hint}
              >
                <button
                  type="button"
                  onClick={() => handleSort(h.key)}
                  className="inline-flex items-center gap-1 hover:text-ink transition-colors"
                  aria-label={`Sort by ${h.label}`}
                  data-active={sortKey === h.key}
                >
                  {h.label}
                  {sortKey === h.key && (
                    <span aria-hidden="true">{sortDir === "asc" ? "▲" : "▼"}</span>
                  )}
                </button>
              </th>
            ))}
            <th className="px-4 py-3 text-left font-medium">Статус</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => {
            const scheduleVar = p.schedule_variance_pct;
            const tier = varianceTier(scheduleVar);
            const icon = TIER_ICON[tier];
            const badge = classifyVariance(scheduleVar);
            return (
              <tr
                key={p.id}
                onClick={() => navigate(`/projects/${p.id}`)}
                className={`border-b border-border last:border-0 hover:bg-bg cursor-pointer transition-colors ${TIER_ROW_BG[tier]}`}
                data-testid={`project-row-${p.id}`}
              >
                <td className="px-4 py-3 text-ink font-medium">{p.name}</td>
                <td className="px-4 py-3 text-right tabular text-ink">
                  {formatMoney(p.total_plan, { compact: true })}
                </td>
                <td className="px-4 py-3 text-right tabular text-ink">
                  {formatMoney(p.total_actual, { compact: true })}
                </td>
                <td
                  className={`px-4 py-3 text-right tabular ${
                    tier === "high" ? "text-warning font-semibold" : "text-ink"
                  }`}
                >
                  <div>
                    {icon && <span className="mr-1">{icon}</span>}
                    {scheduleVar > 0 ? "+" : ""}
                    {formatPercent(scheduleVar, 1)}
                  </div>
                  <div className="text-xs text-muted">
                    {p.schedule_variance_abs > 0 ? "+" : ""}
                    {formatMoney(p.schedule_variance_abs, { compact: true })}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block text-xs px-2 py-1 rounded-pill border ${badge.className}`}
                  >
                    {badge.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
