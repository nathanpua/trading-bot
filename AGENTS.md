# Trading Bot Workspace

Algorithmic trading workspace for US stock market via Alpaca (paper trading).

## Structure

```
~/trading-bot/
├── .venv/              # Python virtualenv (alpaca-py, yfinance, ta, backtrader, etc.)
├── alpaca_client.py    # Alpaca API wrapper (account, orders, positions, market data)
├── indicators.py       # Technical analysis (RSI, MACD, BB, ATR, signals)
├── risk_manager.py     # Position sizing, stop-loss, portfolio risk rules
├── backtest.py         # Backtrader-based strategy backtesting
├── strategies/         # Custom strategy files
├── data/               # Cached market data
├── backtests/          # Backtest results
├── reports/            # Generated reports
├── scripts/            # Cron scripts (premarket_scan.py, daily_summary.py)
└── logs/               # Bot logs
```

## Getting Started

1. Copy `.env.example` to `.env` and add your Alpaca paper trading keys
2. Activate venv: `source ~/trading-bot/.venv/bin/activate`
3. Test connection: `python -c "import alpaca_client; print(alpaca_client.get_account())"`

## Rules

- **Paper trading only** — never switch to live trading without explicit user consent
- **Risk first** — always run risk_manager.assess_trade() before placing orders
- **Monospace tables** — all output to Telegram uses aligned columns, mobile-first
