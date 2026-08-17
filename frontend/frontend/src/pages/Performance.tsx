import { useState, useEffect } from "react";
import { api } from "../api/client";
import fmt from "../lib/format";
import { pnlColor } from "../lib/helpers";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";

interface TradeMetrics {
  total: number; wins: number; losses: number; win_rate: number;
  avg_win: number; avg_loss: number; profit_factor: number | null;
  expectancy: number; max_win_streak: number; max_loss_streak: number;
  total_pnl: number; largest_win: number; largest_loss: number;
  realized_pnl?: number; unrealized_pnl?: number;
}

interface PortfolioMetrics {
  sharpe: number | null; sortino: number | null;
  max_drawdown: number | null; volatility: number | null;
  total_return: number | null; avg_daily_return: number | null;
}

interface MonthlyData {
  month: string; pnl: number; trades: number; wins: number; win_rate: number;
}

interface CumPoint { ts: string; cumulative_pnl: number; symbol: string; pnl: number; }
interface EquityPoint { ts: string; equity: number; }
interface StrategyStat { strategy: string; trades: number; wins: number; win_rate: number; total_pnl: number; }
interface SymbolStat { symbol: string; trades: number; wins: number; win_rate: number; total_pnl: number; }

interface PerfData {
  trade_metrics?: TradeMetrics;
  portfolio_metrics?: PortfolioMetrics;
  overall?: { trades: number; wins: number; losses: number; win_rate: number; total_pnl: number; avg_pnl_pct: number; } | null;
  by_strategy?: StrategyStat[];
  by_symbol?: SymbolStat[];
  monthly?: MonthlyData[];
  cumulative_pnl?: CumPoint[];
  equity_curve?: EquityPoint[];
  closed_trade_count?: number;
  total_trade_count?: number;
  error?: string;
}

function MetricTile({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value" style={{ color: color || "var(--text-primary)" }}>{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

export function Performance() {
  const [data, setData] = useState<PerfData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = () => api.performance().then((d: any) => {
      if (alive) { setData(d as PerfData); setLoading(false); }
    }).catch(() => { if (alive) setLoading(false); });
    load();
    const interval = setInterval(load, 30000); // live: broker equity + open P&L
    return () => { alive = false; clearInterval(interval); };
  }, []);

  if (loading) return <div className="loading">Calculating performance metrics…</div>;
  if (!data || data.error) return <div className="empty-state">Unable to load performance data. {data?.error || ""}</div>;

  const tm = data.trade_metrics;
  const pm = data.portfolio_metrics;

  if (!tm || !pm) return <div className="empty-state">No performance data available yet.</div>;

  const equityData = (data.equity_curve || []).map(e => ({
    ts: e.ts.slice(5), // MM-DD
    equity: e.equity,
  }));

  const cumData = (data.cumulative_pnl || []).map(c => ({
    ts: c.ts.slice(5),
    pnl: c.cumulative_pnl,
  }));

  const monthlyData = (data.monthly || []).map(m => ({
    month: m.month.slice(5), // MM
    pnl: m.pnl,
    trades: m.trades,
  }));

  const sharpeColor = pm.sharpe === null ? "var(--neutral)" :
    pm.sharpe > 1 ? "var(--gain)" : pm.sharpe < 0 ? "var(--loss)" : "var(--warn)";

  return (
    <>
      {/* Key metrics grid */}
      <div className="section">
        <div className="section-title">Portfolio Performance</div>
        <div className="metric-grid">
          <MetricTile label="Total Return" value={pm.total_return !== null ? `${pm.total_return > 0 ? "+" : ""}${pm.total_return}%` : "—"}
            color={pnlColor(pm.total_return || 0)} />
          <MetricTile label="Sharpe Ratio" value={pm.sharpe !== null ? pm.sharpe.toFixed(2) : "—"}
            sub={pm.sharpe !== null ? (pm.sharpe > 1 ? "Good" : pm.sharpe > 0 ? "Positive" : "Negative") : ""}
            color={sharpeColor} />
          <MetricTile label="Sortino Ratio" value={pm.sortino !== null ? pm.sortino.toFixed(2) : "—"}
            sub="downside-adjusted" color={sharpeColor} />
          <MetricTile label="Max Drawdown" value={pm.max_drawdown !== null ? `${pm.max_drawdown}%` : "—"}
            color="var(--loss)" />
          <MetricTile label="Volatility" value={pm.volatility !== null ? `${pm.volatility}%` : "—"}
            sub="annualized" />
          <MetricTile label="Total P&L" value={fmt.signedCurrency(tm.total_pnl)}
            sub={tm.realized_pnl !== undefined && tm.unrealized_pnl !== undefined
              ? `${fmt.signedCurrency(tm.realized_pnl)} realized + ${fmt.signedCurrency(tm.unrealized_pnl)} open`
              : undefined}
            color={pnlColor(tm.total_pnl)} />
        </div>
      </div>

      {/* Trade statistics */}
      <div className="section">
        <div className="section-title">Trade Statistics</div>
        <div className="metric-grid">
          <MetricTile label="Win Rate" value={tm.total > 0 ? `${tm.win_rate}%` : "—"}
            sub={tm.total > 0 ? `${tm.wins}W / ${tm.losses}L` : ""} />
          <MetricTile label="Profit Factor" value={tm.profit_factor !== null ? tm.profit_factor.toFixed(2) : "∞"}
            sub={tm.profit_factor !== null ? (tm.profit_factor > 1.5 ? "Strong" : tm.profit_factor > 1 ? "Profitable" : "Unprofitable") : ""}
            color={tm.profit_factor === null ? "var(--gain)" : tm.profit_factor > 1 ? "var(--gain)" : "var(--loss)"} />
          <MetricTile label="Avg Win" value={fmt.currency(tm.avg_win)} color="var(--gain)" />
          <MetricTile label="Avg Loss" value={fmt.currency(tm.avg_loss)} color="var(--loss)" />
          <MetricTile label="Expectancy" value={fmt.signedCurrency(tm.expectancy)}
            sub="per trade" color={pnlColor(tm.expectancy)} />
          <MetricTile label="Best Streak" value={`${tm.max_win_streak}W`} sub={`Worst: ${tm.max_loss_streak}L`} />
          <MetricTile label="Largest Win" value={fmt.currency(tm.largest_win)} color="var(--gain)" />
          <MetricTile label="Largest Loss" value={fmt.currency(tm.largest_loss)} color="var(--loss)" />
        </div>
      </div>

      {/* Equity curve */}
      {equityData.length > 1 && (
        <div className="section">
          <div className="section-title">Equity Curve</div>
          <div className="card" style={{ height: 280 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#38bdf8" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="ts" tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} />
                <YAxis tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }}
                  domain={["auto", "auto"]} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip contentStyle={{ background: "#0f1419", border: "1px solid #232b38", borderRadius: 6, color: "#e6edf3" }} />
                <Area type="monotone" dataKey="equity" stroke="#38bdf8" strokeWidth={2} fill="url(#eqGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Cumulative P&L */}
      {cumData.length > 0 && (
        <div className="section">
          <div className="section-title">Cumulative Trade P&L</div>
          <div className="card" style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={cumData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <XAxis dataKey="ts" tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} />
                <YAxis tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} tickFormatter={(v) => `$${v}`} />
                <Tooltip contentStyle={{ background: "#0f1419", border: "1px solid #232b38", borderRadius: 6, color: "#e6edf3" }} />
                <ReferenceLine y={0} stroke="#2f3a4a" />
                <Line type="monotone" dataKey="pnl" stroke="#4ade80" strokeWidth={2} dot={{ r: 3, fill: "#4ade80" }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Monthly P&L */}
      {monthlyData.length > 0 && (
        <div className="section">
          <div className="section-title">Monthly P&L</div>
          <div className="card" style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthlyData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <XAxis dataKey="month" tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} />
                <YAxis tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} tickFormatter={(v) => `$${v}`} />
                <Tooltip contentStyle={{ background: "#0f1419", border: "1px solid #232b38", borderRadius: 6, color: "#e6edf3" }}
                  cursor={{ fill: "rgba(56,189,248,0.05)" }} />
                <ReferenceLine y={0} stroke="#2f3a4a" />
                <Bar dataKey="pnl" name="P&L" radius={[4, 4, 0, 0]}>
                  {monthlyData.map((d, i) => (
                    <Cell key={i} fill={d.pnl >= 0 ? "#4ade80" : "#f87171"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Strategy breakdown */}
      {data.by_strategy && data.by_strategy.length > 0 && (
        <div className="section">
          <div className="section-title">Performance by Strategy</div>
          <div className="card" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th className="td-right">Trades</th>
                  <th className="td-right">Win Rate</th>
                  <th className="td-right">Total P&L</th>
                </tr>
              </thead>
              <tbody>
                {data.by_strategy.map((s, i) => (
                  <tr key={i}>
                    <td className="td-mono">{s.strategy}</td>
                    <td className="td-mono td-right">{s.trades}</td>
                    <td className="td-mono td-right" style={{ color: s.win_rate >= 50 ? "var(--gain)" : "var(--loss)" }}>{s.win_rate}%</td>
                    <td className="td-mono td-right" style={{ color: pnlColor(s.total_pnl) }}>{fmt.signedCurrency(s.total_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Symbol breakdown */}
      {data.by_symbol && data.by_symbol.length > 0 && (
        <div className="section">
          <div className="section-title">Performance by Symbol</div>
          <div className="card" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="td-right">Trades</th>
                  <th className="td-right">Win Rate</th>
                  <th className="td-right">Total P&L</th>
                </tr>
              </thead>
              <tbody>
                {data.by_symbol.map((s, i) => (
                  <tr key={i}>
                    <td className="td-mono">{s.symbol}</td>
                    <td className="td-mono td-right">{s.trades}</td>
                    <td className="td-mono td-right" style={{ color: s.win_rate >= 50 ? "var(--gain)" : "var(--loss)" }}>{s.win_rate}%</td>
                    <td className="td-mono td-right" style={{ color: pnlColor(s.total_pnl) }}>{fmt.signedCurrency(s.total_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
