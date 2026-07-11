const fmt = {
  currency(n: number | string | null | undefined, digits = 2): string {
    if (n == null) return "—";
    const v = typeof n === "string" ? parseFloat(n) : n;
    if (isNaN(v)) return "—";
    return v.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  },

  number(n: number | string | null | undefined, digits = 2): string {
    if (n == null) return "—";
    const v = typeof n === "string" ? parseFloat(n) : n;
    if (isNaN(v)) return "—";
    return v.toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  },

  pct(n: number | string | null | undefined, digits = 2): string {
    if (n == null) return "—";
    const v = typeof n === "string" ? parseFloat(n) : n;
    if (isNaN(v)) return "—";
    const mult = Math.abs(v) < 1 ? 100 : 1; // handle 0.02 vs 2.0
    return `${(v * mult).toFixed(digits)}%`;
  },

  signedPct(n: number | string | null | undefined, digits = 2): string {
    if (n == null) return "—";
    const v = typeof n === "string" ? parseFloat(n) : n;
    if (isNaN(v)) return "—";
    const mult = Math.abs(v) < 1 ? 100 : 1;
    const val = v * mult;
    return `${val >= 0 ? "+" : ""}${val.toFixed(digits)}%`;
  },

  signedCurrency(n: number | string | null | undefined, digits = 2): string {
    if (n == null) return "—";
    const v = typeof n === "string" ? parseFloat(n) : n;
    if (isNaN(v)) return "—";
    const sign = v >= 0 ? "+" : "-";
    return `${sign}${Math.abs(v).toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })}`;
  },

  time(ts: string): string {
    try {
      const d = new Date(ts);
      return d.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return ts;
    }
  },

  timeShort(ts: string): string {
    try {
      const d = new Date(ts);
      return d.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
    } catch {
      return ts;
    }
  },
};

export default fmt;
