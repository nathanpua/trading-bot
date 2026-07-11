import { useState, useEffect } from "react";
import { api } from "../api/client";
import type { Portfolio, EquityPoint, Cycle } from "../api/types";
import fmt from "../lib/format";
import { regimeClass, pnlColor } from "../lib/helpers";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";

export function Dashboard() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [cycles, setCycles] = useState<Cycle[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.portfolio(),
      api.equityHistory(),
      api.cycles(5),
    ]).then(([p, e, c]: any) => {
      setPortfolio(p);
      setEquity(e as EquityPoint[]);
      setCycles(c as Cycle[]);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading dashboard…</div>;
  if (!portfolio) return <div className="empty-state">Unable to load portfolio data.</div>;

  const acct = portfolio.account;
  const equityNum = parseFloat(String(acct.equity)) || 0;
  const cashNum = parseFloat(String(acct.cash)) || 0;
  const longVal = parseFloat(String(acct.long_market_value)) || 0;
  const dayPL = parseFloat(String(acct.day_pl)) || 0;
  const dayPLPct = parseFloat(String(acct.day_plpc)) || 0;
  const exposure = equityNum > 0 ? (longVal / equityNum) * 100 : 0;
  const highWater = portfolio.state?.high_water || equityNum;
  const drawdown = equityNum > 0 ? ((equityNum - highWater) / highWater) * 100 : 0;

  const latestCycle = cycles[0];
  const chartData = equity.map((e) => ({
    ts: fmt.timeShort(e.ts),
    equity: e.equity,
  }));

  return (
    <>
      <div className="metric-grid">
        <div className="metric">
          <div className="metric-label">Equity</div>
          <div className="metric-value">{fmt.currency(equityNum)}</div>
          <div className="metric-sub">High: {fmt.currency(highWater)}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Day P&L</div>
          <div className="metric-value" style={{ color: pnlColor(dayPL) }}>
            {fmt.signedCurrency(dayPL)}
          </div>
          <div className="metric-sub">{fmt.signedPct(dayPLPct)}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Cash</div>
          <div className="metric-value">{fmt.currency(cashNum)}</div>
          <div className="metric-sub">{exposure.toFixed(1)}% deployed</div>
        </div>
        <div className="metric">
          <div className="metric-label">Drawdown</div>
          <div className="metric-value" style={{ color: drawdown < -5 ? "var(--loss)" : drawdown < 0 ? "var(--warn)" : "var(--gain)" }}>
            {drawdown.toFixed(2)}%
          </div>
          <div className="metric-sub">
            {portfolio.state?.halted_until ? "⚠ HALTED" : "Kill switch: OK"}
          </div>
        </div>
      </div>

      <div className="section">
        <div className="section-title">Equity Curve</div>
        <div className="card" style={{ height: 280 }}>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#38bdf8" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="ts" tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} />
                <YAxis tick={{ fill: "#5c6677", fontSize: 11 }} axisLine={{ stroke: "#232b38" }} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{ background: "#0f1419", border: "1px solid #232b38", borderRadius: 6, color: "#e6edf3" }}
                  labelStyle={{ color: "#8b96a8" }}
                />
                <Area type="monotone" dataKey="equity" stroke="#38bdf8" strokeWidth={2} fill="url(#equityGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="empty-state">No equity history yet. Data populates as cycles run.</div>
          )}
        </div>
      </div>

      <div className="section">
        <div className="section-title">Regime & Kill Switch</div>
        <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
          {latestCycle && (
            <div className="card" style={{ flex: "1 1 300px" }}>
              <div className="card-header">
                <span className="card-title">Market Regime</span>
                <span className={`regime-badge ${regimeClass(latestCycle.regime?.regime || "neutral")}`}>
                  {latestCycle.regime?.regime || "UNKNOWN"}
                </span>
              </div>
              <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.8 }}>
                {latestCycle.regime?.reasons?.map((r, i) => (
                  <div key={i}>· {r}</div>
                ))}
                <div style={{ marginTop: 8, fontFamily: "var(--font-mono)", fontSize: 12 }}>
                  Risk multiplier: {latestCycle.regime?.risk_multiplier}× · VIX: {latestCycle.regime?.vix}
                </div>
              </div>
            </div>
          )}
          <div className="card" style={{ flex: "1 1 300px" }}>
            <div className="card-header">
              <span className="card-title">Kill Switch</span>
              <span className={`badge ${portfolio.state?.halted_until ? "badge-loss" : "badge-gain"}`}>
                {portfolio.state?.halted_until ? "HALTED" : "OK"}
              </span>
            </div>
            <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.8 }}>
              <div>Halt reason: {portfolio.state?.halt_reason || "None"}</div>
              <div>Day baseline: {fmt.currency(portfolio.state?.day_start_equity)}</div>
              <div>Positions tracked: {Object.keys(portfolio.state?.positions || {}).length}</div>
            </div>
          </div>
        </div>
      </div>

      {latestCycle && (
        <div className="section">
          <div className="section-title">Latest Cycle Report</div>
          <div className="cycle-report">{latestCycle.report}</div>
        </div>
      )}
    </>
  );
}
