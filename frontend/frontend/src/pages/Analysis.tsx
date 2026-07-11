import { useState, useEffect } from "react";
import { api } from "../api/client";
import type { TradeStats, MemoryResult } from "../api/types";
import fmt from "../lib/format";
import { pnlColor } from "../lib/helpers";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";

export function Analysis() {
  const [stats, setStats] = useState<TradeStats | null>(null);
  const [loading, setLoading] = useState(true);

  // Memory search
  const [query, setQuery] = useState("");
  const [memResults, setMemResults] = useState<MemoryResult[]>([]);
  const [memStatus, setMemStatus] = useState<boolean | null>(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    api.stats().then((s: any) => {
      setStats(s);
      setLoading(false);
    }).catch(() => setLoading(false));
    api.memoryStatus().then((s: any) => setMemStatus(s.connected)).catch(() => {});
  }, []);

  const searchMemory = () => {
    if (!query.trim()) return;
    setSearching(true);
    api.memorySearch(query, 5).then((r) => {
      setMemResults((r as { results: MemoryResult[] }).results);
      setSearching(false);
    }).catch(() => setSearching(false));
  };

  if (loading) return <div className="loading">Loading analysis…</div>;

  const overall = stats?.overall;

  return (
    <>
      {/* Overall stats tiles */}
      <div className="metric-grid">
        <div className="metric">
          <div className="metric-label">Total Trades</div>
          <div className="metric-value">{overall?.trades ?? 0}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Win Rate</div>
          <div className="metric-value" style={{ color: overall && overall.win_rate >= 50 ? "var(--gain)" : "var(--warn)" }}>
            {overall ? `${overall.win_rate}%` : "—"}
          </div>
          <div className="metric-sub">
            {overall ? `${overall.wins}W / ${overall.losses}L` : ""}
          </div>
        </div>
        <div className="metric">
          <div className="metric-label">Total P&L</div>
          <div className="metric-value" style={{ color: pnlColor(overall?.total_pnl) }}>
            {overall ? fmt.signedCurrency(overall.total_pnl) : "—"}
          </div>
        </div>
        <div className="metric">
          <div className="metric-label">Avg P&L %</div>
          <div className="metric-value" style={{ color: pnlColor(overall?.avg_pnl_pct) }}>
            {overall ? fmt.signedPct(overall.avg_pnl_pct) : "—"}
          </div>
        </div>
      </div>

      {/* Charts */}
      <div className="section">
        <div className="section-title">Performance by Strategy</div>
        <div className="card" style={{ height: stats?.by_strategy?.length ? 240 : 100 }}>
          {stats?.by_strategy?.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stats.by_strategy} layout="vertical" margin={{ left: 20, right: 20 }}>
                <XAxis type="number" tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} />
                <YAxis type="category" dataKey="strategy" tick={{ fill: "#8b96a8", fontSize: 12 }} axisLine={{ stroke: "#232b38" }} width={80} />
                <Tooltip
                  contentStyle={{ background: "#0f1419", border: "1px solid #232b38", borderRadius: 6, color: "#e6edf3" }}
                  cursor={{ fill: "rgba(56,189,248,0.05)" }}
                />
                <Bar dataKey="win_rate" name="Win Rate %" radius={[0, 4, 4, 0]}>
                  {stats.by_strategy.map((_, i) => (
                    <Cell key={i} fill="#38bdf8" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="empty-state">No closed trades yet.</div>
          )}
        </div>
      </div>

      <div className="section">
        <div className="section-title">P&L by Symbol</div>
        <div className="card" style={{ height: stats?.by_symbol?.length ? 280 : 100 }}>
          {stats?.by_symbol?.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stats.by_symbol} margin={{ left: 0, right: 20, top: 10 }}>
                <XAxis dataKey="symbol" tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} />
                <YAxis tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} />
                <Tooltip
                  contentStyle={{ background: "#0f1419", border: "1px solid #232b38", borderRadius: 6, color: "#e6edf3" }}
                  cursor={{ fill: "rgba(56,189,248,0.05)" }}
                />
                <Bar dataKey="total_pnl" name="Total P&L" radius={[4, 4, 0, 0]}>
                  {stats.by_symbol.map((s, i) => (
                    <Cell key={i} fill={s.total_pnl >= 0 ? "#4ade80" : "#f87171"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="empty-state">No closed trades yet.</div>
          )}
        </div>
      </div>

      {/* Lessons */}
      {stats?.recent_lessons && stats.recent_lessons.length > 0 && (
        <div className="section">
          <div className="section-title">Lessons Learned</div>
          <div className="card">
            {stats.recent_lessons.map((l, i) => (
              <div key={i} style={{
                padding: "10px 0",
                borderBottom: i < stats.recent_lessons!.length - 1 ? "1px solid var(--border)" : "none",
              }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                  <span className="badge badge-neutral">{l.category}</span>
                  <span className={`badge ${l.confidence === "high" ? "badge-gain" : l.confidence === "low" ? "badge-warn" : "badge-neutral"}`}>
                    {l.confidence}
                  </span>
                </div>
                <div style={{ color: "var(--text-primary)", fontSize: 13 }}>{l.lesson}</div>
                {l.evidence && (
                  <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 4 }}>{l.evidence}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Supermemory search */}
      <div className="section">
        <div className="section-title">
          Semantic Memory
          <span style={{ marginLeft: "auto", fontSize: 12 }}>
            <span className={`badge ${memStatus ? "badge-gain" : "badge-neutral"}`}>
              {memStatus === null ? "…" : memStatus ? "Connected" : "Offline"}
            </span>
          </span>
        </div>
        <div className="card">
          <div className="search-box">
            <input
              type="text"
              placeholder="Search past findings, analyst insights, regime patterns…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && searchMemory()}
            />
            <button className="btn" onClick={searchMemory} disabled={searching}>
              {searching ? "…" : "Search"}
            </button>
          </div>

          {memResults.length > 0 ? (
            memResults.map((r, i) => (
              <div key={i} className="memory-result">
                <div className="memory-result-meta">
                  <span className="memory-similarity">{(r.similarity * 100).toFixed(0)}% match</span>
                  {r.metadata?.ts ? <span>· {fmt.time(String(r.metadata.ts))}</span> : null}
                  {r.metadata?.type ? <span>· {String(r.metadata.type)}</span> : null}
                  {r.metadata?.symbol ? <span>· {String(r.metadata.symbol)}</span> : null}
                </div>
                <div style={{ color: "var(--text-primary)", fontSize: 13 }}>{r.memory}</div>
              </div>
            ))
          ) : memResults.length === 0 && !searching ? (
            <div className="empty-state">
              Search across Supermemory for past trade findings, lessons, and analyst insights.
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
