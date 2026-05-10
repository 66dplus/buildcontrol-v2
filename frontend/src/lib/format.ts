/**
 * Money + percent + date formatters matching the design (RUB, Russian locale).
 */

export function formatMoney(value: number, opts?: { compact?: boolean }): string {
  const n = Number.isFinite(value) ? value : 0;
  if (opts?.compact && Math.abs(n) >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M ₽`;
  }
  if (opts?.compact && Math.abs(n) >= 1_000) {
    return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K ₽`;
  }
  return `${new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 0,
  }).format(n)} ₽`;
}

export function formatPercent(value: number, fractionDigits = 0): string {
  if (!Number.isFinite(value)) return "—";
  return `${value.toFixed(fractionDigits)}%`;
}

export function variancePct(plan: number, actual: number): number {
  if (!plan) return 0;
  return ((actual - plan) / plan) * 100;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("ru-RU", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
