import { useState, useEffect } from "react";
import { Dashboard } from "./pages/Dashboard";
import { Positions } from "./pages/Positions";
import { Trades } from "./pages/Trades";
import { Analysis } from "./pages/Analysis";
import { AICycles } from "./pages/AICycles";
import { api } from "./api/client";

type Page = "dashboard" | "ai-cycles" | "positions" | "trades" | "analysis";

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: "dashboard", label: "Dashboard", icon: "▤" },
  { id: "ai-cycles", label: "AI Cycles", icon: "⚖" },
  { id: "positions", label: "Positions", icon: "◈" },
  { id: "trades", label: "Trades", icon: "↕" },
  { id: "analysis", label: "Analysis", icon: "⊙" },
];

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [marketOpen, setMarketOpen] = useState<boolean | null>(null);

  useEffect(() => {
    api.portfolio().then((d: any) => setMarketOpen(d.market_open)).catch(() => {});
  }, []);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>Trading Floor</h1>
          <p>Paper Trading Dashboard</p>
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
          <div>Market: {marketOpen === null ? "…" : marketOpen ? "OPEN" : "CLOSED"}</div>
          <div style={{ marginTop: 4 }}>Alpaca Paper · GLM 4.6</div>
        </div>
      </aside>
      <main className="main">
        {page === "dashboard" && <Dashboard />}
        {page === "ai-cycles" && <AICycles />}
        {page === "positions" && <Positions />}
        {page === "trades" && <Trades />}
        {page === "analysis" && <Analysis />}
      </main>
    </div>
  );
}
