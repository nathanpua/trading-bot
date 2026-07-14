import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";
import fmt from "../lib/format";

interface StrategyInfo {
  id: string;
  name: string;
  theme: string;
  description: string;
  enabled: boolean;
}

interface StrategyScore {
  score: number;
  signal: string;
  name: string;
  theme: string;
}

interface ScanResult {
  symbol: string;
  composite_score: number;
  composite_signal: string;
  bullish_count: number;
  bearish_count: number;
  neutral_count: number;
  price: number;
  strategy_scores: Record<string, StrategyScore>;
}

interface ScanResponse {
  timestamp?: string;
  symbols_scanned?: number;
  strategy_count?: number;
  summary?: {
    bullish: number;
    bearish: number;
    neutral: number;
    top_bullish: Array<{ symbol: string; score: number; strategies: number }>;
    top_bearish: Array<{ symbol: string; score: number; strategies: number }>;
  };
  results?: ScanResult[];
  error?: string;
}

function signalColor(signal: string): string {
  if (signal === "bullish") return "var(--gain)";
  if (signal === "bearish") return "var(--loss)";
  return "var(--neutral)";
}

function scoreBar(score: number) {
  // score is -1 to +1; map to 0-100% width from center
  const pct = Math.abs(score) * 50;
  const isPositive = score >= 0;
  return (
    <div className="score-bar">
      <div className="score-bar-track">
        <div
          className="score-bar-fill"
          style={{
            width: `${pct}%`,
            marginLeft: isPositive ? "50%" : `${50 - pct}%`,
            background: isPositive ? "var(--gain)" : "var(--loss)",
          }}
        />
      </div>
      <div className="score-bar-center" />
    </div>
  );
}

function StrategyCard({ id, score, signal, name, theme }: StrategyScore & { id: string }) {
  return (
    <div className="strategy-score-row" style={{ borderLeft: `3px solid ${signalColor(signal)}` }}>
      <div className="strategy-score-header">
        <span className="strategy-score-name">{name}</span>
        <span className="strategy-score-theme">{theme}</span>
        <span className={`badge ${signal === "bullish" ? "badge-gain" : signal === "bearish" ? "badge-loss" : "badge-neutral"}`} style={{ marginLeft: "auto" }}>
          {signal}
        </span>
        <span className="strategy-score-val" style={{ color: signalColor(signal) }}>
          {score > 0 ? "+" : ""}{score.toFixed(3)}
        </span>
      </div>
    </div>
  );
}

function SymbolDetail({ result }: { result: ScanResult }) {
  const [expanded, setExpanded] = useState(false);
  const signal = result.composite_signal;
  const score = result.composite_score;

  return (
    <div className="card" style={{ padding: 0, marginBottom: 8, overflow: "hidden" }}>
      <div
        className="symbol-row"
        onClick={() => setExpanded(!expanded)}
        style={{ cursor: "pointer", padding: "12px 16px" }}
      >
        <span className="symbol-name" style={{ fontFamily: "var(--font-mono)", fontSize: 16, fontWeight: 600, minWidth: 60 }}>
          {result.symbol}
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--text-dim)", minWidth: 70 }}>
          ${result.price?.toFixed(2)}
        </span>
        <div style={{ flex: 1, maxWidth: 200 }}>{scoreBar(score)}</div>
        <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: signalColor(signal), minWidth: 50 }}>
          {score > 0 ? "+" : ""}{score.toFixed(2)}
        </span>
        <span className={`badge ${signal === "bullish" ? "badge-gain" : signal === "bearish" ? "badge-loss" : "badge-neutral"}`}>
          {signal.toUpperCase()}
        </span>
        <span style={{ fontSize: 11, color: "var(--text-dim)", minWidth: 80 }}>
          {result.bullish_count}B / {result.bearish_count}S / {result.neutral_count}N
        </span>
        <span style={{ color: "var(--text-dim)", fontSize: 12 }}>{expanded ? "▲" : "▼"}</span>
      </div>
      {expanded && (
        <div style={{ padding: "0 16px 12px", borderTop: "1px solid var(--border)" }}>
          {Object.entries(result.strategy_scores || {})
            .sort(([, a], [, b]) => Math.abs(b.score) - Math.abs(a.score))
            .map(([sid, s]) => (
              <StrategyCard key={sid} id={sid} {...s} />
            ))}
        </div>
      )}
    </div>
  );
}

export function Strategies() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [scanData, setScanData] = useState<ScanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [symbolQuery, setSymbolQuery] = useState("");

  const loadStrategies = useCallback(() => {
    api.strategies().then((d: any) => {
      setStrategies(d.strategies || []);
    }).catch(() => {});
  }, []);

  const runScan = useCallback((limit = 20) => {
    setScanning(true);
    api.strategyScan(limit).then((d: any) => {
      setScanData(d);
      setScanning(false);
    }).catch(() => setScanning(false));
  }, []);

  const scanSymbol = useCallback(() => {
    if (!symbolQuery.trim()) return;
    setScanning(true);
    api.strategyScanSymbol(symbolQuery.trim().toUpperCase()).then((d: any) => {
      if (d.error) {
        setScanning(false);
        return;
      }
      setScanData({
        results: [d],
        symbols_scanned: 1,
        strategy_count: Object.keys(d.strategy_scores || {}).length,
        summary: {
          bullish: d.composite_signal === "bullish" ? 1 : 0,
          bearish: d.composite_signal === "bearish" ? 1 : 0,
          neutral: d.composite_signal === "neutral" ? 1 : 0,
          top_bullish: [],
          top_bearish: [],
        },
      });
      setScanning(false);
    }).catch(() => setScanning(false));
  }, [symbolQuery]);

  useEffect(() => {
    loadStrategies();
    runScan(20);
    setLoading(false);
  }, [loadStrategies, runScan]);

  if (loading) return <div className="loading">Loading strategies…</div>;

  const summary = scanData?.summary;

  return (
    <>
      {/* Strategy registry */}
      <div className="section">
        <div className="section-title">Alpha Strategies ({strategies.length})</div>
        <div className="strategy-grid">
          {strategies.map((s) => (
            <div key={s.id} className="card strategy-card-info" style={{ padding: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontFamily: "var(--font-display)", fontSize: 13, fontWeight: 600 }}>
                  {s.name}
                </span>
                <span className={`badge ${s.enabled ? "badge-gain" : "badge-neutral"}`} style={{ marginLeft: "auto" }}>
                  {s.enabled ? "ON" : "OFF"}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 4 }}>
                {s.theme} · {s.id}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                {s.description}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Scan controls */}
      <div className="section">
        <div className="section-title">Symbol Scanner</div>
        <div className="search-box" style={{ marginBottom: 12 }}>
          <input
            type="text"
            placeholder="Scan a symbol (e.g. NVDA)…"
            value={symbolQuery}
            onChange={(e) => setSymbolQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && scanSymbol()}
          />
          <button className="btn" onClick={scanSymbol} disabled={scanning}>Scan Symbol</button>
          <button className="btn" onClick={() => runScan(20)} disabled={scanning} style={{ marginLeft: 4 }}>
            {scanning ? "Scanning…" : "Scan Universe"}
          </button>
        </div>

        {/* Summary tiles */}
        {summary && (
          <div className="metric-grid" style={{ marginBottom: 16 }}>
            <div className="metric">
              <div className="metric-label">Bullish</div>
              <div className="metric-value" style={{ color: "var(--gain)" }}>{summary.bullish}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Bearish</div>
              <div className="metric-value" style={{ color: "var(--loss)" }}>{summary.bearish}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Neutral</div>
              <div className="metric-value" style={{ color: "var(--neutral)" }}>{summary.neutral}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Strategies</div>
              <div className="metric-value">{scanData?.strategy_count || strategies.length}</div>
            </div>
          </div>
        )}

        {/* Results */}
        {scanData?.error && (
          <div className="empty-state">Scan error: {scanData.error}</div>
        )}
        {scanData?.results && scanData.results.length > 0 ? (
          <div>
            {scanData.results
              .sort((a, b) => b.composite_score - a.composite_score)
              .map((r) => <SymbolDetail key={r.symbol} result={r} />)}
          </div>
        ) : !scanning ? (
          <div className="empty-state">No scan results. Click "Scan Universe" to analyze.</div>
        ) : (
          <div className="loading">Scanning {scanData?.symbols_scanned || ""} symbols…</div>
        )}
      </div>
    </>
  );
}
