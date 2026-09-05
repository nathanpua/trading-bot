# 🤖 Autonomous Trading Bot

A fully automated, **deterministic-by-design** algorithmic trading system for the
US stock market. It scans a configurable universe, ranks opportunities by
multi-indicator confluence, risk-governs every trade with hard math, and manages
positions with trailing stops — running unattended on a schedule.

> **⚠️ Paper trading only.** The system defaults to Alpaca's paper-trading
> endpoint and ships with a `paper: true` safety lock in `config.yaml`. Every
> order is a dry run unless you explicitly pass `--execute`. **This is not
> financial advice** — it's an educational engineering project.

---

## ✨ Highlights

- **Autonomous decision loop** — `REGIME → KILL-SWITCH → SCAN → MANAGE → GOVERN → EXECUTE → REPORT`. Every risk check is hard math, never LLM-interpreted.
- **Two systematic entry paths** — *confluence* (oversold bounce, 3-of-5 indicators agreeing) and *momentum* (trend-continuation via ADX/MACD/RSI).
- **Risk-first** — ATR-based stops, 2:1 reward/risk targets, position sizing capped by both risk % and concentration %, plus portfolio-level kill switches.
- **Regime awareness** — reads VIX/VIXY fear gauge + SPY trend to scale position sizes (RISK-ON / NEUTRAL / RISK-OFF).
- **Full technical stack** — RSI, MACD, SMA(20/50), Bollinger Bands, ATR, ADX, Stochastic, OBV.
- **Backtesting** — Backtrader-powered backtests with Sharpe, max-drawdown, and win-rate metrics.
- **Persistent memory** — a SQLite trade journal (with full-text search) **and** an optional Supermemory-backed semantic layer that recalls past findings, regime patterns, and lessons.
- **Two execution modes** — a fully autonomous engine (`autonomous_engine.py`) and a "trading floor" pipeline where a human/LLM desk chief decides and a governed executor (`trading_floor_execute.py`) enforces.

---

## 🏗️ Architecture

```
                         ┌─────────────────────────────────────┐
                         │        config.yaml (all tunables)    │
                         └────────────────┬────────────────────┘
                                          │
                 ┌────────────────────────▼────────────────────────┐
                 │              autonomous_engine.py                │
                 │           (the decision loop / "brain")          │
                 │                                                 │
                 │  REGIME ──► KILL-SWITCH ──► SCAN ENTRIES        │
                 │      ──► MANAGE EXITS ──► GOVERN ──► EXECUTE     │
                 │      ──► REPORT (console + JSON log)             │
                 └───┬──────────┬──────────┬──────────┬───────────┘
                     │          │          │          │
          ┌──────────▼──┐ ┌─────▼─────┐ ┌──▼──────┐ ┌─▼──────────┐
          │ indicators  │ │  risk_    │ │ finnhub │ │ alpaca_    │
          │   .py       │ │ manager.py│ │ client  │ │  client    │
          │ (RSI/MACD/  │ │ (sizing,  │ │ (quotes,│ │ (orders,   │
          │  ATR/ADX/…) │ │  stops)   │ │  news)  │ │  positions)│
          └─────────────┘ └───────────┘ └─────────┘ └────────────┘
                                                     │
                                          ┌──────────┴──────────┐
                                  ┌───────▼────────┐    ┌───────▼────────┐
                                  │ trade_journal  │    │ trade_memory   │
                                  │   .py          │    │   .py          │
                                  │ (SQLite + FTS5)│    │ (Supermemory   │
                                  │                │    │  semantic)     │
                                  └────────────────┘ └────────────────┘
```

### Module guide

| File | Role |
|------|------|
| [`autonomous_engine.py`](autonomous_engine.py) | **The brain.** One cycle = assess market regime → check kill switches → scan for entries → manage open positions → risk-govern & execute → emit a report. Designed to run on cron. |
| [`alpaca_client.py`](alpaca_client.py) | Broker wrapper: account info, positions, market/limit/stop/bracket orders, historical bars (with local CSV caching). |
| [`finnhub_client.py`](finnhub_client.py) | Primary market-data feed: real-time quotes, OHLCV candles, market news, and company news. Rate-limited to respect the free tier. |
| [`indicators.py`](indicators.py) | Computes the full indicator suite and a 0–5 confluence *buy/sell score* (RSI + MACD + SMA cross + Bollinger + Stochastic). |
| [`risk_manager.py`](risk_manager.py) | Position sizing (`shares = portfolio × risk% / stop_distance`), ATR-based stop/take-profit, and portfolio exposure checks. |
| [`trade_journal.py`](trade_journal.py) | SQLite store of every trade, lesson, and cycle — queryable by strategy/symbol with full-text search. |
| [`trade_memory.py`](trade_memory.py) | Optional semantic memory via Supermemory; recalls analyst findings and lessons at the start of each cycle. |
| [`backtest.py`](backtest.py) / [`backtest_analysis.py`](backtest_analysis.py) | Backtrader backtests. `backtest_analysis.py` is a corrected harness that fixes two upstream bugs (see its header docstring). |
| [`config.yaml`](config.yaml) | **All tunables** — risk limits, strategy thresholds, the trade universe, regime thresholds. No code changes needed to tune. |

### Scripts (`scripts/`)

| Script | What it does |
|--------|--------------|
| `scan_universe.py` | Whole-market technical scanner — ranks ~45 symbols by confluence. |
| `premarket_scan.py` | Compact pre-market signal table for a watchlist (cron-friendly, silent on error). |
| `daily_summary.py` | End-of-day P&L summary (account, positions, exposure). |
| `news_scan.py` | Finnhub market + per-symbol company news. |
| `catalyst_scan.py` | Earnings calendar + economic calendar + news. |
| `macro_snapshot.py` / `macro_snapshot_local.py` | Cross-asset macro breadth table (via yfinance / local cache). |
| `breadth.py` | Market breadth: how many names are above their 20-SMA. |
| `trading_floor_state.py` | Dumps complete portfolio + technicals + regime as JSON. |
| `trading_floor_context.py` | Combines state + memory recall + journal stats into one context block. |
| `trading_floor_execute.py` | **Governed executor**: takes a JSON trade plan, risk-gates each action, submits bracket orders. |
| `execute_trade_plan.py` | Standalone bracket-order builder/submitter for a symbol list. |
| `seed_memory.py` | Seeds Supermemory with sample analyst findings. |

---

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.11** (3.10+ should work)
- Free accounts & API keys for:
  - [**Alpaca**](https://app.alpaca.markets/paper/dashboard/overview) — broker + historical data (**required**)
  - [**Finnhub**](https://finnhub.io/register) — real-time quotes + news (**required**)
  - [Alpha Vantage](https://www.alphavantage.co/support/#api-key) — fallback data source (optional)
  - [Supermemory](https://supermemory.ai) — semantic memory (optional)

### 2. Clone & install

```bash
git clone https://github.com/nathanpua/trading-bot.git
cd trading-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure keys

```bash
cp .env.example .env
# Edit .env and paste in your Alpaca + Finnhub keys
```

### 4. Verify the connection

```bash
python -c "import alpaca_client as a; print(a.get_account())"
```

You should see a JSON dump of your paper-trading account (equity, cash, etc.).

### 5. Run a cycle

```bash
# Dry run — scans, decides, but places NO orders (the safe default)
python autonomous_engine.py

# Live paper-trading execution — submits real orders to your PAPER account
python autonomous_engine.py --execute

# P&L snapshot only (no scan, no decisions)
python autonomous_engine.py --phase report
```

---

## ⚙️ How a Trading Cycle Works

Each invocation of `autonomous_engine.py` runs one complete cycle:

```
1. REGIME       Read VIX/VIXY (fear) + SPY vs SMA50 (trend) → scale all
                position sizes by a risk multiplier (0.25×–1.0×).

2. KILL-SWITCH  Track equity high-water + daily baseline.
                • -2% intraday  → HALT new entries (same-day cooldown)
                • -8% drawdown  → DEFENSIVE (2-day halt)
                Exits still run — always protect capital.

3. SCAN ENTRIES Score the universe (config.yaml → strategy.universe).
                • CONFLUENCE path: buy_score ≥ threshold + MACD positive
                • MOMENTUM path:   ADX ≥ 25 + MACD positive + RSI 40–75
                Skip bearish confluence; require uptrend (price > SMA50).

4. MANAGE EXITS For every open position:
                • Signal-flip exit (MACD neg + below SMA20)
                • Trailing stop (activates at +1R, trails by 1 ATR)
                • Time stop (exit if flat/negative after N days)

5. GOVERN       Each candidate → ATR stop + 2:1 target, size by
                risk % × regime multiplier, capped by concentration %
                and max total exposure (no position-count limit).

6. EXECUTE      Submit bracket orders (market + stop-loss + take-profit).
                DRY RUN by default; --execute submits to your paper account.

7. REPORT       Print a monospace briefing + persist a JSON decision log.
```

All of this is configurable in [`config.yaml`](config.yaml) — no code edits needed.

---

## 🔧 Configuration

Everything tunable lives in [`config.yaml`](config.yaml). Key sections:

```yaml
risk:
  max_risk_per_trade: 0.02     # risk 2% of portfolio per trade
  max_concentration: 0.25      # max 25% in one position
  max_positions: null         # null = unlimited concurrent positions
  max_daily_loss: 0.02         # -2% in a day → HALT
  max_drawdown: 0.08           # -8% from peak → DEFENSIVE
  atr_stop_mult: 1.5           # stop = entry − 1.5×ATR
  reward_ratio: 2.0            # target = 2× stop distance

strategy:
  entry_threshold: 2           # min confluence score (of 5) to qualify
  require_uptrend: true        # only enter above SMA50
  universe:                    # what the scanner evaluates
    semis:     [NVDA, AMD, MRVL, ...]
    mega:      [AAPL, MSFT, GOOGL, ...]
    high_beta: [COIN, PLTR, MSTR, ...]
    etf:       [SPY, QQQ, IWM, ...]

regime:
  vix_risk_on_threshold: 18    # below this → favors RISK-ON
  vix_risk_off_threshold: 25   # above this → RISK-OFF
```

---

## ⏰ Running Unattended (cron)

The bot is designed to run on a schedule. `run_cycle.sh` is a thin cron wrapper:

```bash
# crontab -e
# Pre-market scan at 9:00 AM ET (14:00 UTC), Mon–Fri
0 14 * * 1-5  ~/trading-bot/run_cycle.sh >> ~/trading-bot/logs/cron.log 2>&1

# (or run the full engine — it self-gates on is_market_open())
*/15 14-20 * * 1-5  ~/trading-bot/run_cycle.sh >> ~/trading-bot/logs/cron.log 2>&1
```

`run_cycle.sh` always passes `--execute`, but the engine **self-gates on market
hours**: during closed hours it only reports and places no orders. This makes
`--execute` safe at any time — the engine is the market-hours authority.

### Running on a VPS with Hermes Agent (scheduled Telegram delivery)

For a production deployment with scheduled reports delivered to your phone,
see **[docs/VPS-HERMES.md](docs/VPS-HERMES.md)**. It covers the full setup:
installing [Hermes Agent](https://hermes-agent.nousresearch.com/) on a VPS,
connecting it to Telegram, and using its `--no-agent` cron mode to run the
bot's scripts on a schedule and deliver clean monospace tables to your chat —
no LLM tokens spent on routine runs.

---

## 🧪 Backtesting

```bash
# Single-symbol backtest with the default signal strategy
python -c "import backtest as b; print(b.format_backtest_report(b.run_backtest('AAPL', limit=750)))"

# Edge validation across the whole universe
python smoke_test.py
```

`backtest_analysis.py` documents and fixes two bugs in the stock Backtrader
`PandasData` feed (it doesn't expose custom dataframe columns as lines, so
confluence scores silently read as 0 → zero trades). See its header docstring.

---

## 📊 The "Trading Floor" Pipeline (alternative to autonomous engine)

For a human/LLM-in-the-loop workflow, use the three-stage pipeline:

```bash
# 1. Gather state (positions + technicals + regime) as JSON
python scripts/trading_floor_state.py > state.json

# 2. Build a context block (state + memory + journal) for a desk chief to read
python scripts/trading_floor_context.py

# 3. The desk chief produces a JSON trade plan, then the GOVERNED executor runs it:
echo '[{"action":"BUY","symbol":"MU","thesis":"memory supercycle","risk_pct":0.02}]' \
  | python scripts/trading_floor_execute.py            # dry run
echo '[{"action":"BUY","symbol":"MU","thesis":"...","risk_pct":0.02}]' \
  | python scripts/trading_floor_execute.py --execute  # live paper submit
```

The executor **always** re-validates sizing, concentration, and portfolio limits
regardless of what the plan says — the desk chief *decides*, the executor *governs*.

---

## 🛡️ Safety Model

| Layer | What it protects |
|-------|------------------|
| `paper: true` in config | Hard lock against live trading |
| `--execute` opt-in | Default is always dry run |
| `is_market_open()` gate | No entries outside market hours |
| Daily-loss kill switch | -2% → same-day entry halt |
| Drawdown kill switch | -8% → 2-day defensive halt |
| Risk-based sizing | Never more than `max_risk_per_trade` at risk |
| Concentration cap | No single position over `max_concentration` |
| Portfolio caps | `max_total_exposure` enforced pre-submit (`max_positions` optional, null = unlimited) |

---

## 🖥️ Web Dashboard

A real-time trading dashboard with portfolio overview, positions, trade
history, and analysis — deployed as a Dockerized FastAPI + React app.

```
Trading Bot scripts ──► Dashboard (read-only) ──► Browser (Tailscale)
(~/trading-bot)         Docker :8010               http://100.92.170.88:8081
```

### Features

- **Dashboard** — Equity gauge, equity curve chart, market regime badge,
  kill-switch status, latest cycle report
- **Positions** — Live positions with entry/current/P&L, stop levels,
  position detail cards
- **Trades** — Historical trade journal with expandable thesis/reasoning,
  filterable by strategy/status/outcome
- **Analysis** — Win rate by strategy, P&L by symbol charts, lessons
  learned, and Supermemory semantic search

### Deploy

```bash
cd frontend
sg docker -c "docker compose up -d --build"
```

The dashboard is read-only — it never places trades or modifies bot state.
It imports the bot's Python modules (`alpaca_client`, `trade_journal`,
`trade_memory`) to query live data. Access via Caddy on your Tailscale IP.

---

## 📁 Project Layout

```
trading-bot/
├── autonomous_engine.py      # ← the decision loop (start here)
├── alpaca_client.py          # broker API wrapper
├── finnhub_client.py         # market-data feed
├── indicators.py             # technical analysis + signal scoring
├── risk_manager.py           # sizing, stops, portfolio rules
├── trade_journal.py          # SQLite trade journal (FTS5 search)
├── trade_memory.py           # Supermemory semantic memory (optional)
├── backtest.py               # Backtrader backtesting
├── backtest_analysis.py      # corrected backtest harness
├── config.yaml               # ALL tunable parameters
├── run_cycle.sh              # cron wrapper
├── smoke_test.py             # data-depth + trade verification
├── requirements.txt
├── .env.example              # key template → copy to .env
├── scripts/                  # scanner, summaries, trading-floor pipeline
├── frontend/                 # web dashboard (Dockerized FastAPI + React)
│   ├── Dockerfile            # multi-stage build (React → FastAPI)
│   ├── docker-compose.yml
│   ├── backend/              # FastAPI API server
│   └── frontend/             # React + Vite + Recharts SPA
├── data/                     # (gitignored) cached market-data CSVs
├── reports/                  # (gitignored) cycle logs & assessments
└── logs/                     # (gitignored) runtime logs
```

---

## ⚠️ Disclaimer

This software is for **educational and research purposes only**. It is not
investment advice. Algorithmic trading involves substantial risk of loss.
Past performance (including backtests) does not guarantee future results.
The authors are not responsible for any financial losses. Use entirely at
your own risk.

## 📄 License

[MIT](LICENSE) © Nathan Pua

## Local Dev Workflow (Mac → GitHub → VPS)

1. Develop on the Mac in `~/trading-bot` (venv: `source .venv/bin/activate`, Python 3.11 via uv).
2. Commit and push to `main` — same repo, `git push origin main`.
3. The VPS watcher (`~/.hermes/scripts/trading_pull_watcher.sh`, every 5 min) fast-forwards the live copy, runs a health check (module imports + config parse), restarts the dashboard when bot code/config changed, and posts the new commits to Discord.
4. Secrets live only in `.env` per machine (gitignored): Alpaca, LSE, GLM keys. Never commit them.
