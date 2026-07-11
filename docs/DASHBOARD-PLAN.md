# Trading Bot Dashboard — Implementation Plan

## Overview

A web dashboard for the trading bot, following the same architecture pattern
as the spending-tracker: **Dockerized FastAPI backend + React frontend**,
reverse-proxied through Caddy on the Tailscale IP.

The dashboard is a **read-only observability layer** — it queries data from
the bot's existing modules and APIs. It does not place trades or modify state.

---

## Data Sources

| Source | What it provides | How we access it |
|--------|-----------------|------------------|
| **Alpaca API** | Live account equity, cash, positions, order history, historical bars | `alpaca_client.py` (import directly) |
| **Trade Journal SQLite** | Historical trades, thesis, P&L, strategy tags, lessons, cycle log | `reports/trade_journal.db` |
| **Cycle Reports** | Regime, kill-switch status, entries/exits decisions, equity snapshots | `reports/autonomous/*.json` |
| **Bot State** | High-water mark, halt status, position stops | `reports/autonomous/state.json` |
| **Supermemory** | Semantic trade memory (past findings, lessons, analyst insights) | `trade_memory.py` (import directly) |
| **Finnhub** | Real-time quotes for current prices | `finnhub_client.py` |

---

## Architecture (same pattern as spending-tracker)

```
trading-bot/
├── (existing bot files — untouched)
├── dashboard/
│   ├── backend/
│   │   ├── Dockerfile              # Multi-stage: React build → FastAPI
│   │   ├── requirements.txt        # fastapi, uvicorn, httpx, pydantic
│   │   ├── app/
│   │   │   ├── main.py             # FastAPI entrypoint + serves frontend dist
│   │   │   ├── config.py           # Settings (paths, API key loading)
│   │   │   ├── api/
│   │   │   │   ├── portfolio.py    # /api/portfolio — account, positions, equity
│   │   │   │   ├── trades.py       # /api/trades — historical trades from journal
│   │   │   │   ├── cycles.py       # /api/cycles — cycle reports, regime history
│   │   │   │   ├── analysis.py     # /api/analysis — stats, memory recall, lessons
│   │   │   │   └── health.py       # /api/health
│   │   │   └── services/
│   │   │       ├── alpaca_service.py  # Wraps alpaca_client.py calls
│   │   │       ├── journal_service.py # Queries trade_journal.db
│   │   │       └── memory_service.py  # Wraps trade_memory.py
│   │   └── .env.example
│   ├── frontend/
│   │   ├── package.json            # React 18 + Vite + Recharts + react-router
│   │   ├── vite.config.ts          # Dev proxy → backend :8010
│   │   ├── index.html
│   │   └── src/
│   │       ├── main.tsx
│   │       ├── App.tsx             # Layout + route switching
│   │       ├── api/
│   │       │   ├── client.ts       # Fetch wrapper
│   │       │   └── types.ts        # TypeScript interfaces
│   │       ├── pages/
│   │       │   ├── Dashboard.tsx   # Overview: equity curve, regime, positions
│   │       │   ├── Positions.tsx   # Current positions with live P&L
│   │       │   ├── Trades.tsx      # Historical trade log with thesis/reasoning
│   │       │   ├── Analysis.tsx    # Win rates, strategy breakdown, lessons
│   │       │   └── Memory.tsx      # Supermemory recall search
│   │       ├── components/
│   │       │   ├── EquityChart.tsx     # Portfolio equity over time (Recharts)
│   │       │   ├── PositionCard.tsx    # Single position with P&L
│   │       │   ├── RegimeBadge.tsx     # Risk-on/off/neutral indicator
│   │       │   ├── TradeRow.tsx        # Trade log table row
│   │       │   ├── StatsCard.tsx       # Win rate, avg R/R, total P&L
│   │       │   └── KillSwitchIndicator.tsx
│   │       └── styles.css
│   ├── docker-compose.yml
│   └── .env.example
```

---

## Backend API Design

### `/api/portfolio` — Live snapshot
```json
{
  "account": {
    "equity": 97133.93,
    "cash": 83131.07,
    "buying_power": 371732.29,
    "day_pl": 0.0,
    "day_plpc": 0.0,
    "long_market_value": 14002.86,
    "market_status": "closed"
  },
  "positions": [
    {
      "symbol": "DASH",
      "qty": 73,
      "entry_price": 191.99,
      "current_price": 191.82,
      "market_value": 14002.86,
      "unrealized_pl": -12.41,
      "unrealized_plpc": -0.001,
      "stop_price": 179.33,
      "target_price": null,
      "entry_date": "2026-07-11T10:31:41Z"
    }
  ],
  "state": {
    "high_water": 97133.93,
    "halted_until": null,
    "halt_reason": null,
    "day_start_equity": 97133.93
  }
}
```

### `/api/portfolio/equity-history` — Equity curve data points
Returns time series of equity snapshots from cycle reports (and optionally
Alpaca portfolio history API for longer history).

### `/api/trades` — Historical trade journal
```
GET /api/trades?limit=50&symbol=NVDA&strategy=momentum&status=closed
```
Returns trades from the SQLite journal with thesis, outcome, P&L, strategy,
regime, and tags.

### `/api/trades/stats` — Aggregate performance
Overall win rate, total P&L, avg P&L %, breakdowns by strategy and by symbol.

### `/api/cycles` — Cycle history
```
GET /api/cycles?limit=20
```
Returns recent cycle reports: regime, halt status, entries, exits, equity,
timestamp.

### `/api/analysis/memory?q=<query>` — Supermemory recall
Semantic search across past trade memories, findings, and lessons.

### `/api/analysis/lessons` — Journal lessons
Recent lessons from the SQLite journal with FTS5 search.

---

## Frontend Pages

### 1. Dashboard (overview)
- **Equity gauge**: Current equity vs. high-water mark (drawdown indicator)
- **Equity chart**: Portfolio value over time (Recharts AreaChart)
- **Regime badge**: RISK-ON / NEUTRAL / RISK-OFF with VIXY + SPY trend
- **Kill switch status**: Green (OK) / Red (halted) with reason
- **Position summary cards**: Count, total exposure %, day P&L
- **Latest cycle briefing**: Monospace text from the most recent cycle

### 2. Positions
- Table of current positions: symbol, qty, entry, current price, P&L $, P&L %,
  stop price, time held
- Unrealized P&L bar chart per position
- Position detail expand: entry thesis (from journal), trailing stop state

### 3. Trades (history)
- Sortable/filterable table: date, symbol, side, strategy, regime, P&L, outcome
- Expandable rows showing the full **trade thesis / reasoning**
- Filter by symbol, strategy, outcome, date range
- Aggregate stats bar at top (total trades, win rate, total P&L)

### 4. Analysis
- **Win rate by strategy** (bar chart)
- **P&L by symbol** (horizontal bar chart)
- **Cumulative P&L over time** (line chart)
- **Recent lessons** list with category + confidence badges
- **Supermemory search box**: query past findings semantically

---

## Deployment

### Docker setup (mirrors spending-tracker)
```yaml
# dashboard/docker-compose.yml
services:
  trading-dashboard:
    build: ./backend
    container_name: trading-dashboard
    restart: unless-stopped
    ports:
      - "8010:8010"
    env_file:
      - .env
    volumes:
      # Read-only access to bot data — the dashboard never writes
      - ../reports:/app/reports:ro
      - ../data:/app/data:ro
      # Bot .env for Alpaca/Finnhub keys
      - ../.env:/app/.env:ro
```

The container imports the bot's Python modules directly (added to PYTHONPATH),
so it can call `alpaca_client.get_account()`, `trade_journal.get_stats()`, etc.

### Caddy reverse proxy
Add to the existing Caddyfile:
```
# Trading Bot Dashboard - Tailscale only
http://100.92.170.88:8081 {
    reverse_proxy localhost:8010
}
```

### Key design decisions
- **Read-only**: Dashboard never modifies bot state or places trades
- **Imports bot modules**: Backend PYTHONPATH includes `/app` mapped to the bot
  root, so `import alpaca_client`, `import trade_journal`, etc. work directly
- **Same stack as spending-tracker**: FastAPI + React + Vite + Recharts, no
  new technologies to learn
- **Tailscale-only access**: Same network security as spending-tracker
- **Docker isolated**: Doesn't interfere with the bot's venv or cron jobs

---

## Implementation Order

| Phase | What | Est. effort |
|-------|------|-------------|
| **1** | Backend scaffold: FastAPI app, config, Docker setup, health endpoint | 30 min |
| **2** | Backend APIs: portfolio, trades, cycles, analysis endpoints | 1-2 hrs |
| **3** | Frontend scaffold: Vite + React + routing + API client | 30 min |
| **4** | Dashboard page: equity chart, regime, positions summary | 1 hr |
| **5** | Positions + Trades pages | 1 hr |
| **6** | Analysis page: stats charts + memory search | 1 hr |
| **7** | Dockerize, Caddy proxy, deploy, verify | 30 min |

---

## Key Considerations

1. **Trade journal is currently empty** on this VPS (fresh migration). The
   bot populates it during live trading cycles. The trades page will show
   data once the bot runs during market hours. The Alpaca orders API
   (`get_orders()`) provides real trade history immediately.

2. **Equity history**: The bot only started logging cycle equity on this VPS.
   For a richer equity curve, we can pull portfolio history from Alpaca's API
   (`/v2/account/portfolio/timeseries`).

3. **Bot module imports in Docker**: The backend Dockerfile must install the
   bot's Python dependencies (alpaca-py, requests, PyYAML, etc.) since it
   imports those modules. We'll add the bot's `requirements.txt` to the
   dashboard backend's install step.

4. **Rate limits**: Alpaca and Finnhub have free-tier rate limits. The
   dashboard backend should cache API responses (e.g., 30-60s TTL) to avoid
   burning through quotas on page refresh.
