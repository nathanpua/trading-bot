import { useState, useEffect } from "react";
import { Dashboard } from "./pages/Dashboard";
import { Positions } from "./pages/Positions";
import { Trades } from "./pages/Trades";
import { Analysis } from "./pages/Analysis";
import { AICycles } from "./pages/AICycles";
import { Strategies } from "./pages/Strategies";
import { Performance } from "./pages/Performance";
import { api } from "./api/client";

type Page = "dashboard" | "performance" | "ai-cycles" | "strategies" | "positions" | "trades" | "analysis";

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: "dashboard", label: "Dashboard", icon: "▤" },
  { id: "performance", label: "Performance", icon: "♯" },
  { id: "ai-cycles", label: "AI Cycles", icon: "⚖" },
  { id: "strategies", label: "Strategies", icon: "Σ" },
  { id: "positions", label: "Positions", icon: "◈" },
  { id: "trades", label: "Trades", icon: "↕" },
  { id: "analysis", label: "Analysis", icon: "⊙" },
];

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [marketOpen, setMarketOpen] = useState<boolean | null>(null);
  const [equity, setEquity] = useState<string>("");
  const [regime, setRegime] = useState<string>("");
  const [dayPL, setDayPL] = useState<string>("");

  useEffect(() => {
    const poll = () => {
      api.portfolio().then((d: any) => {
        setMarketOpen(d.market_open?.is_open ?? false);
        const a = d.account;
        setEquity(String(a?.equity || ""));
        setDayPL(String(a?.day_plpc || ""));
      }).catch(() => {});
      api.aiCycleLatest().then((d: any) => {
        setRegime(d?.regime || "");
      }).catch(() => {});
    };
    poll();
    const interval = setInterval(poll, 30000);
    return () => clearInterval(interval);
  }, []);

  const fmtEquity = equity ? `$${parseFloat(equity).toLocaleString("en-US", { maximumFractionDigits: 0 })}` : "…";
  const fmtDayPL = dayPL ? `${(parseFloat(dayPL) * 100).toFixed(2)}%` : "—";

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>
            <span className={`brand-dot ${marketOpen ? "" : "off"}`} />
            Trading Floor
          </h1>
          <p>AI Paper Trading</p>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`nav-item ${page === n.id ? "active" : ""}`}
              onClick={() => setPage(n.id)}
            >
              <span className="nav-icon">{n.icon}</span>
              {n.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="footer-line">
            <span className={`status-dot ${marketOpen ? "open" : "closed"}`} />
            Market {marketOpen ? "OPEN" : "CLOSED"}
          </div>
          <div className="footer-line">Alpaca Paper · GLM 5.2</div>
        </div>
      </aside>
      <main className="main">
        <div className="desk-bar">
          <div className="desk-bar-item">
            <span className={`desk-bar-dot ${marketOpen ? "open" : "closed"}`} />
            <span className="desk-bar-value">{marketOpen ? "LIVE" : "CLOSED"}</span>
          </div>
          <div className="desk-bar-item">
            <span className="desk-bar-label">Equity</span>
            <span className="desk-bar-value">{fmtEquity}</span>
          </div>
          <div className="desk-bar-item">
            <span className="desk-bar-label">Day</span>
            <span className="desk-bar-value" style={{
              color: parseFloat(dayPL) >= 0 ? "var(--gain)" : "var(--loss)"
            }}>{fmtDayPL}</span>
          </div>
          {regime && (
            <div className="desk-bar-item">
              <span className="desk-bar-label">Regime</span>
              <span className="desk-bar-value">{regime}</span>
            </div>
          )}
          <div className="desk-bar-item">
            <span className="desk-bar-label">Model</span>
            <span className="desk-bar-value">GLM 5.2</span>
          </div>
        </div>
        <div className="main-content">
          {page === "dashboard" && <Dashboard />}
          {page === "performance" && <Performance />}
          {page === "ai-cycles" && <AICycles />}
          {page === "strategies" && <Strategies />}
          {page === "positions" && <Positions />}
          {page === "trades" && <Trades />}
          {page === "analysis" && <Analysis />}
        </div>
      </main>
    </div>
  );
}
