import { useState, useEffect } from "react";
import { api } from "../api/client";
import type { Portfolio } from "../api/types";
import fmt from "../lib/format";
import { pnlColor } from "../lib/helpers";

export function Positions() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.portfolio().then((p: any) => {
      setPortfolio(p);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading positions…</div>;
  if (!portfolio || !portfolio.positions.length) {
    return <div className="empty-state">No open positions.</div>;
  }

  const positions = portfolio.positions;
  const botPositions = portfolio.state?.positions || {};

  return (
    <>
      <div className="section">
        <div className="section-title">
          Open Positions
          <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-dim)" }}>
            {positions.length} position{positions.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="td-right">Qty</th>
                  <th className="td-right">Entry</th>
                  <th className="td-right">Current</th>
                  <th className="td-right">Market Value</th>
                  <th className="td-right">Unrealized P&L</th>
                  <th className="td-right">P&L %</th>
                  <th className="td-right">Stop</th>
                  <th>Stop Status</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const sym = pos.symbol;
                  const entry = parseFloat(String(pos.avg_entry_price));
                  const cur = parseFloat(String(pos.current_price));
                  const mv = parseFloat(String(pos.market_value));
                  const upl = parseFloat(String(pos.unrealized_pl));
                  const uplPct = parseFloat(String(pos.unrealized_plpc));
                  const botState = botPositions[sym];
                  const stop = botState?.stop;
                  const entryHigh = botState?.high || entry;

                  return (
                    <tr key={sym}>
                      <td style={{ fontWeight: 600, fontFamily: "var(--font-display)" }}>{sym}</td>
                      <td className="td-mono td-right">{fmt.number(parseFloat(String(pos.qty)), 0)}</td>
                      <td className="td-mono td-right">{fmt.currency(entry)}</td>
                      <td className="td-mono td-right">{fmt.currency(cur)}</td>
                      <td className="td-mono td-right">{fmt.currency(mv)}</td>
                      <td className="td-mono td-right" style={{ color: pnlColor(upl) }}>
                        {fmt.signedCurrency(upl)}
                      </td>
                      <td className="td-mono td-right" style={{ color: pnlColor(uplPct) }}>
                        {fmt.signedPct(uplPct)}
                      </td>
                      <td className="td-mono td-right">{stop ? fmt.currency(stop) : "—"}</td>
                      <td>
                        {stop && (
                          <span className={`badge ${cur <= stop * 1.02 ? "badge-loss" : cur < entry ? "badge-warn" : "badge-gain"}`}>
                            {cur <= stop * 1.02 ? "NEAR STOP" : cur < entry ? "UNDERWATER" : "PROFIT"}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="section">
        <div className="section-title">Position Detail</div>
        <div className="metric-grid">
          {positions.map((pos) => {
            const sym = pos.symbol;
            const entry = parseFloat(String(pos.avg_entry_price));
            const cur = parseFloat(String(pos.current_price));
            const upl = parseFloat(String(pos.unrealized_pl));
            const uplPct = parseFloat(String(pos.unrealized_plpc));
            const botState = botPositions[sym];
            const stop = botState?.stop;
            const entryDate = botState?.entry_date;

            return (
              <div key={sym} className="metric">
                <div className="metric-label" style={{ fontFamily: "var(--font-display)", color: "var(--accent)" }}>
                  {sym}
                </div>
                <div className="metric-value" style={{ color: pnlColor(upl), fontSize: 20 }}>
                  {fmt.signedCurrency(upl)}
                </div>
                <div className="metric-sub">{fmt.signedPct(uplPct)}</div>
                <div className="pnl-bar">
                  <div
                    className="pnl-bar-fill"
                    style={{
                      width: `${Math.min(Math.abs(uplPct) * 500, 100)}%`,
                      background: pnlColor(upl),
                    }}
                  />
                </div>
                {stop && (
                  <div className="metric-sub" style={{ marginTop: 8 }}>
                    Stop: {fmt.currency(stop)} · Entry: {fmt.currency(entry)}
                  </div>
                )}
                {entryDate && (
                  <div className="metric-sub">Since {fmt.time(entryDate)}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
