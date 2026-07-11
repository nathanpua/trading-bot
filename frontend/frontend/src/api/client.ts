const BASE = "";

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(`${BASE}${url}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${url}`);
  return res.json();
}

export const api = {
  portfolio: () => fetchJSON("/api/portfolio"),
  equityHistory: () => fetchJSON("/api/portfolio/equity-history"),
  trades: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return fetchJSON(`/api/trades${qs ? "?" + qs : ""}`);
  },
  tradeStats: () => fetchJSON("/api/trades/stats"),
  cycles: (limit = 20) => fetchJSON(`/api/cycles?limit=${limit}`),
  stats: () => fetchJSON("/api/analysis/stats"),
  memorySearch: (q: string, limit = 5) =>
    fetchJSON(`/api/analysis/memory?q=${encodeURIComponent(q)}&limit=${limit}`),
  memoryStatus: () => fetchJSON("/api/analysis/memory/status"),
  health: () => fetchJSON("/api/health"),
};
