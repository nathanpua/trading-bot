import { useState, useEffect } from "react";
import { api } from "../api/client";
import type { Trade } from "../api/types";
import fmt from "../lib/format";
import { pnlColor } from "../lib/helpers";

export function Trades() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [filters, setFilters] = useState({ strategy: "", status: "", outcome: "" });

  useEffect(() => {
    const params: Record<string, string> = { limit: "100" };
    if (filters.strategy) params.strategy = filters.strategy;
    if (filters.status) params.status = filters.status;
    if (filters.outcome) params.outcome = filters.outcome;
    api.trades(params).then((t) => {
      setTrades(t as Trade[]);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [filters]);

  const strategies = [...new Set(trades.map((t) => t.strategy).filter(Boolean))];
  const outcomes = [...new Set(trades.map((t) => t.outcome).filter(Boolean))];

  if (loading) return <div className="loading">Loading trades…</div>;

  return (
    <>
      <div className="section">
        <div className="section-title">
          Trade History
          <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-dim)" }}>
            {trades.length} records
          </span>
        </div>

        <div className="filters">
          <select
            value={filters.strategy}
            onChange={(e) => setFilters({ ...filters, strategy: e.target.value })}
          >
            <option value="">All Strategies</option>
            {strategies.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            value={filters.status}
            onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          >
            <option value="">All Status</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
          <select
            value={filters.outcome}
            onChange={(e) => setFilters({ ...filters, outcome: e.target.value })}
          >
            <option value="">All Outcomes</option>
            {outcomes.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>

        {trades.length === 0 ? (
          <div className="empty-state">
            No trades in journal yet. Trade history populates as the bot executes during market hours.
            <br />Alpaca order history is also available via the Positions page.
          </div>
        ) : (
          <div className="card">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th className="td-right">Qty</th>
                    <th className="td-right">Entry</th>
                    <th className="td-right">Exit</th>
                    <th className="td-right">P&L</th>
                    <th>Strategy</th>
                    <th>Regime</th>
                    <th>Outcome</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => (
                    <>
                      <tr
                        key={t.id}
                        onClick={() => setExpanded(expanded === t.id ? null : t.id)}
                        style={{ cursor: t.thesis ? "pointer" : "default" }}
                      >
                        <td className="td-mono">{fmt.time(t.ts)}</td>
                        <td style={{ fontWeight: 600, fontFamily: "var(--font-display)" }}>{t.symbol}</td>
                        <td>
                          <span className={`badge ${t.side === "BUY" ? "badge-gain" : "badge-loss"}`}>
                            {t.side}
                          </span>
                        </td>
                        <td className="td-mono td-right">{t.qty ? fmt.number(t.qty, 0) : "—"}</td>
                        <td className="td-mono td-right">{t.entry_price ? fmt.currency(t.entry_price) : "—"}</td>
                        <td className="td-mono td-right">{t.exit_price ? fmt.currency(t.exit_price) : "—"}</td>
                        <td className="td-mono td-right" style={{ color: pnlColor(t.pnl_dollars) }}>
                          {t.pnl_dollars != null ? fmt.signedCurrency(t.pnl_dollars) : "—"}
                        </td>
                        <td>{t.strategy || "—"}</td>
                        <td>
                          {t.regime && (
                            <span className="badge badge-neutral" style={{ fontSize: 10 }}>
                              {t.regime}
                            </span>
                          )}
                        </td>
                        <td>
                          {t.outcome && (
                            <span className={`badge ${
                              t.outcome === "win" || t.outcome === "target_hit" ? "badge-gain" :
                              t.outcome === "loss" || t.outcome === "stopped" ? "badge-loss" :
                              "badge-neutral"
                            }`}>
                              {t.outcome}
                            </span>
                          )}
                        </td>
                        <td style={{ color: "var(--text-dim)" }}>
                          {t.thesis ? (expanded === t.id ? "▲" : "▼") : ""}
                        </td>
                      </tr>
                      {expanded === t.id && t.thesis && (
                        <tr key={`thesis-${t.id}`}>
                          <td colSpan={11} style={{ padding: 0, border: "none" }}>
                            <div className="trade-thesis">
                              <strong style={{ color: "var(--accent)" }}>Thesis:</strong> {t.thesis}
                              {t.tags && t.tags !== "[]" && (
                                <div style={{ marginTop: 8, fontSize: 12 }}>
                                  <strong style={{ color: "var(--text-dim)" }}>Tags:</strong> {t.tags}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
