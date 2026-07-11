export function regimeClass(regime: string): string {
  const r = regime.toUpperCase();
  if (r.includes("ON")) return "regime-risk-on";
  if (r.includes("OFF")) return "regime-risk-off";
  if (r.includes("DEFENSIVE")) return "regime-defensive";
  return "regime-neutral";
}

export function pnlClass(n: number | string | null | undefined): string {
  if (n == null) return "";
  const v = typeof n === "string" ? parseFloat(n) : n;
  if (isNaN(v) || v === 0) return "";
  return v > 0 ? "gain" : "loss";
}

export function pnlColor(n: number | string | null | undefined): string {
  if (n == null) return "var(--neutral)";
  const v = typeof n === "string" ? parseFloat(n) : n;
  if (isNaN(v) || v === 0) return "var(--neutral)";
  return v > 0 ? "var(--gain)" : "var(--loss)";
}
