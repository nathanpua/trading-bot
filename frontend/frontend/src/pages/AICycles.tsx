import { useState, useEffect } from "react";
import { api } from "../api/client";
import type { AICycle, AICycleAction, AICycleBriefing } from "../api/types";
import fmt from "../lib/format";

const AGENT_META: Record<string, { label: string; icon: string; color: string }> = {
  macro_analyst: { label: "Macro", icon: "🌐", color: "var(--accent)" },
  news_analyst: { label: "News", icon: "📰", color: "#fbbf24" },
  technical_analyst: { label: "Technical", icon: "📊", color: "#4ade80" },
  risk_analyst: { label: "Risk", icon: "⚠", color: "#f87171" },
  memory_analyst: { label: "Memory", icon: "🧠", color: "#a855f7" },
};

function actionIcon(act: string): string {
  const a = act.toUpperCase();
  if (a === "BUY") return "▸";
  if (a === "SELL" || a === "CLOSE") return "✗";
  if (a === "HOLD") return "○";
  return "?";
}

function actionColor(act: string): string {
  const a = act.toUpperCase();
  if (a === "BUY") return "var(--gain)";
  if (a === "SELL" || a === "CLOSE") return "var(--loss)";
  return "var(--neutral)";
}

function convictionBadge(conv: string): string {
  const c = conv.toLowerCase();
  if (c === "high") return "badge-gain";
  if (c === "low") return "badge-loss";
  return "badge-neutral";
}

function BriefingCard({ agentKey, briefing }: { agentKey: string; briefing: AICycleBriefing }) {
  const meta = AGENT_META[agentKey] || { label: agentKey, icon: "•", color: "var(--text-secondary)" };
  const isError = briefing.status === "error";

  return (
    <div className="card briefing-card" style={{ borderColor: isError ? "var(--border)" : meta.color + "33" }}>
      <div className="briefing-header" style={{ borderLeft: `3px solid ${meta.color}` }}>
        <span className="briefing-icon">{meta.icon}</span>
        <span className="briefing-label">{meta.label}</span>
        {briefing.confidence && !isError && (
          <span className={`badge ${convictionBadge(briefing.confidence)}`} style={{ marginLeft: "auto" }}>
            {briefing.confidence}
          </span>
        )}
        {isError && <span className="badge badge-loss" style={{ marginLeft: "auto" }}>FAIL</span>}
      </div>
      {isError ? (
        <div className="briefing-body" style={{ color: "var(--text-dim)" }}>
          {briefing.error || "Agent unavailable"}
        </div>
      ) : (
        <div className="briefing-body">
          {briefing.assessment && <p className="briefing-assessment">{briefing.assessment}</p>}
          {/* Agent-specific highlights */}
          {agentKey === "macro_analyst" && (briefing as any).regime && (
            <div className="briefing-tags">
              <span className={`regime-badge regime-${(briefing as any).regime.toLowerCase().replace("-", "")}`}>
                {(briefing as any).regime}
              </span>
              {(briefing as any).risk_multiplier !== undefined && (
                <span className="tag-mono">risk_mult: {(briefing as any).risk_multiplier}</span>
              )}
            </div>
          )}
          {agentKey === "news_analyst" && (briefing as any).market_sentiment && (
            <div className="briefing-tags">
              <span className={`badge ${(briefing as any).market_sentiment === "bullish" ? "badge-gain" : (briefing as any).market_sentiment === "bearish" ? "badge-loss" : "badge-neutral"}`}>
                {(briefing as any).market_sentiment}
              </span>
            </div>
          )}
          {agentKey === "risk_analyst" && (
            <div className="briefing-tags">
              {(briefing as any).risk_level && (
                <span className={`badge ${
                  (briefing as any).risk_level === "low" ? "badge-gain" :
                  (briefing as any).risk_level === "extreme" || (briefing as any).risk_level === "high" ? "badge-loss" :
                  "badge-warn"
                }`}>{(briefing as any).risk_level}</span>
              )}
              {(briefing as any).portfolio_recommendation && (
                <span className="tag-mono">{(briefing as any).portfolio_recommendation}</span>
              )}
            </div>
          )}
          {/* Actionable items for news analyst */}
          {agentKey === "news_analyst" && (briefing as any).actionable && (briefing as any).actionable.length > 0 && (
            <ul className="briefing-list">
              {(briefing as any).actionable.slice(0, 3).map((a: any, i: number) => (
                <li key={i}>
                  <span style={{ color: a.signal === "bullish" ? "var(--gain)" : a.signal === "bearish" ? "var(--loss)" : "var(--neutral)" }}>
                    {a.signal === "bullish" ? "▲" : a.signal === "bearish" ? "▼" : "•"}
                  </span>{" "}
                  {a.headline}
                  {a.symbols?.length > 0 && <span className="tag-symbols"> {a.symbols.join(", ")}</span>}
                </li>
              ))}
            </ul>
          )}
          {/* Position verdicts for technical analyst */}
          {agentKey === "technical_analyst" && (briefing as any).positions && (briefing as any).positions.length > 0 && (
            <ul className="briefing-list">
              {(briefing as any).positions.map((p: any, i: number) => (
                <li key={i}>
                  <strong>{p.symbol}</strong>{" "}
                  <span style={{ color: actionColor(p.action) }}>{p.action}</span>
                  {p.note && <span className="briefing-note"> — {p.note}</span>}
                </li>
              ))}
            </ul>
          )}
          {/* Risk position risks */}
          {agentKey === "risk_analyst" && (briefing as any).position_risks && (briefing as any).position_risks.length > 0 && (
            <ul className="briefing-list">
              {(briefing as any).position_risks.map((r: any, i: number) => (
                <li key={i}>
                  <strong>{r.symbol}</strong> {r.risk} (severity: {r.severity}) →{" "}
                  <span style={{ color: actionColor(r.recommendation) }}>{r.recommendation}</span>
                </li>
              ))}
            </ul>
          )}
          {/* Memory pattern warning */}
          {agentKey === "memory_analyst" && (briefing as any).pattern_warning && (briefing as any).pattern_warning !== "null" && (
            <div className="pattern-warning">⚠ {(briefing as any).pattern_warning}</div>
          )}
          {agentKey === "memory_analyst" && (briefing as any).relevant_lessons && (briefing as any).relevant_lessons.length > 0 && (
            <ul className="briefing-list">
              {(briefing as any).relevant_lessons.slice(0, 2).map((l: any, i: number) => (
                <li key={i}>{l.lesson}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function CycleDetail({ cycle }: { cycle: AICycle }) {
  const briefings = cycle.briefings || {};
  const briefingKeys = ["macro_analyst", "news_analyst", "technical_analyst", "risk_analyst", "memory_analyst"]
    .filter(k => k in briefings);

  return (
    <div className="ai-cycle-detail">
      {/* Analysis synthesis */}
      {cycle.analysis && Object.keys(cycle.analysis).length > 0 && (
        <div className="card" style={{ marginBottom: "16px" }}>
          <div className="card-header">
            <span className="card-title">Desk Chief Analysis</span>
            {cycle.confidence && (
              <span className={`badge ${convictionBadge(cycle.confidence)}`}>{cycle.confidence}</span>
            )}
          </div>
          <div className="analysis-grid">
            {cycle.analysis.market_read && (
              <div className="analysis-item">
                <span className="analysis-label">Market Read</span>
                <p>{cycle.analysis.market_read}</p>
              </div>
            )}
            {cycle.analysis.key_consensus && (
              <div className="analysis-item">
                <span className="analysis-label">Consensus</span>
                <p>{cycle.analysis.key_consensus}</p>
              </div>
            )}
            {cycle.analysis.key_disagreement && cycle.analysis.key_disagreement !== "none" && (
              <div className="analysis-item">
                <span className="analysis-label">Disagreement</span>
                <p style={{ color: "var(--warn)" }}>{cycle.analysis.key_disagreement}</p>
              </div>
            )}
            {cycle.analysis.risk_outlook && (
              <div className="analysis-item">
                <span className="analysis-label">Risk Outlook</span>
                <p>{cycle.analysis.risk_outlook}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Actions */}
      {cycle.actions && cycle.actions.length > 0 && (
        <div className="section" style={{ marginTop: "0" }}>
          <div className="section-title">Actions Decided</div>
          <div className="actions-grid">
            {cycle.actions.map((a: AICycleAction, i: number) => (
              <div key={i} className="card action-card" style={{ borderLeft: `3px solid ${actionColor(a.action)}` }}>
                <div className="action-header">
                  <span className="action-icon" style={{ color: actionColor(a.action) }}>
                    {actionIcon(a.action)}
                  </span>
                  <span className="action-type" style={{ color: actionColor(a.action) }}>{a.action}</span>
                  {a.symbol && <span className="action-symbol">{a.symbol}</span>}
                  {a.conviction && (
                    <span className={`badge ${convictionBadge(a.conviction)}`} style={{ marginLeft: "auto" }}>
                      {a.conviction}
                    </span>
                  )}
                </div>
                {a.thesis && <p className="action-thesis">{a.thesis}</p>}
                {a.supporting_analysts && a.supporting_analysts.length > 0 && (
                  <div className="action-supporters">
                    {a.supporting_analysts.map((s, j) => {
                      const m = AGENT_META[Object.keys(AGENT_META).find(k => k.includes(s) || s.includes(k.split("_")[0])) || ""];
                      return (
                        <span key={j} className="supporter-tag">
                          {m?.icon || "•"} {s}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Analyst briefings grid */}
      {briefingKeys.length > 0 && (
        <div className="section">
          <div className="section-title">Analyst Briefings</div>
          <div className="briefings-grid">
            {briefingKeys.map(key => (
              <BriefingCard key={key} agentKey={key} briefing={briefings[key]} />
            ))}
          </div>
        </div>
      )}

      {/* Execution results */}
      {cycle.execution?.results?.length > 0 && (
        <div className="section">
          <div className="section-title">
            Execution ({cycle.execution.executed ? "LIVE" : "DRY RUN"})
          </div>
          <div className="card" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Symbol</th>
                  <th>Status</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {cycle.execution.results.map((r: any, i: number) => (
                  <tr key={i}>
                    <td style={{ color: actionColor(r.action || "") }}>{r.action || "?"}</td>
                    <td className="td-mono">{r.symbol || "—"}</td>
                    <td>
                      <span className={`badge ${
                        r.status === "submitted" || r.status === "executed" ? "badge-gain" :
                        r.status === "error" ? "badge-loss" :
                        r.status === "skipped" ? "badge-warn" : "badge-neutral"
                      }`}>{r.status}</span>
                    </td>
                    <td className="td-mono" style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                      {r.entry && `${r.qty}sh @ $${r.entry}`}
                      {r.reason && r.reason}
                      {r.error && r.error}
                      {r.stop && ` stop=$${r.stop}`}
                      {r.target && ` tgt=$${r.target}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Full text report */}
      {cycle.report && (
        <div className="section">
          <div className="section-title">Full Report</div>
          <div className="cycle-report">{cycle.report}</div>
        </div>
      )}
    </div>
  );
}

export function AICycles() {
  const [cycles, setCycles] = useState<AICycle[]>([]);
  const [selected, setSelected] = useState<number>(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.aiCycles(30).then((data: any) => {
      setCycles(data as AICycle[]);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading AI cycles…</div>;
  if (cycles.length === 0) {
    return (
      <div className="empty-state">
        <p>No AI cycles yet. The multi-agent trading floor hasn't run.</p>
        <p style={{ marginTop: 8, fontSize: 12 }}>
          Run <code style={{ color: "var(--accent)" }}>./run_trading_floor.sh</code> to start.
        </p>
      </div>
    );
  }

  const active = cycles[selected];

  return (
    <>
      {/* Cycle selector — horizontal scroll list */}
      <div className="cycle-selector">
        {cycles.map((c, i) => (
          <button
            key={i}
            className={`cycle-pill ${i === selected ? "active" : ""}`}
            onClick={() => setSelected(i)}
          >
            <span className="cycle-pill-time">{fmt.timeShort(c.ts)}</span>
            <span className="cycle-pill-summary" title={c.summary}>
              {c.summary.slice(0, 50) || `${c.actions.length} actions`}
            </span>
            <span className="cycle-pill-meta">
              {c.mode === "trading_floor" ? "5-agents" : "single"}
            </span>
          </button>
        ))}
      </div>

      {/* Active cycle summary bar */}
      <div className="cycle-summary-bar">
        <div className="cycle-summary-main">
          <span className="cycle-summary-ts">{fmt.time(active.ts)}</span>
          <span className="badge badge-neutral">{active.model}</span>
          {active.elapsed_seconds && (
            <span style={{ fontSize: 11, color: "var(--text-dim)" }}>{active.elapsed_seconds.toFixed(0)}s</span>
          )}
          {active.regime && (
            <span className={`regime-badge regime-${active.regime.toLowerCase().replace("-", "")}`}>
              {active.regime}
            </span>
          )}
        </div>
        <div className="cycle-summary-port">
          <span>Equity: {fmt.currency(active.equity)}</span>
          <span>Positions: {active.position_count}</span>
          <span>Candidates: {active.candidate_count}</span>
        </div>
      </div>

      <CycleDetail cycle={active} />
    </>
  );
}
