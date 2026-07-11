"""Find the Alpaca free-tier cutoff: how far back / what end-date works."""
import os
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from datetime import datetime, timedelta, timezone

key, sec = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
env_path = os.path.join(os.path.dirname(__file__), ".env")
for line in open(env_path):
    line = line.strip()
    if line.startswith("ALPACA_API_KEY=") and not line.startswith("#"):
        key = line.split("=", 1)[1].strip().strip("'\"")
    elif line.startswith("ALPACA_SECRET_KEY=") and not line.startswith("#"):
        sec = line.split("=", 1)[1].strip().strip("'\"")

client = StockHistoricalDataClient(api_key=key, secret_key=sec)

def try_pull(symbol, start, end, limit=1000, label=""):
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(1, TimeFrameUnit.Day),
            start=start, end=end, limit=limit,
        )
        df = client.get_stock_bars(req).df
        n = len(df)
        rng = ""
        if n:
            ts = df.index.get_level_values("timestamp") if "timestamp" in df.index.names else df.index
            rng = f"  {ts.min().date()} -> {ts.max().date()}"
        print(f"  [{label}] rows={n}{rng}")
        return n
    except Exception as e:
        print(f"  [{label}] ERROR: {str(e)[:120]}")
        return 0

print("=== Cutoff search: end date offsets, AAPL, 2yr lookback ===")
for days_ago in (0, 1, 2, 3, 4, 7, 15):
    end = datetime.now(timezone.utc) - timedelta(days=days_ago)
    start = end - timedelta(days=730)
    try_pull("AAPL", start, end, 1000, f"end -{days_ago}d")

print("\n=== Max history: end=2026-06-19, vary lookback ===")
end = datetime(2026, 6, 19, tzinfo=timezone.utc)
for yrs in (0.5, 1, 2, 3, 5):
    start = end - timedelta(days=int(365 * yrs))
    try_pull("AAPL", start, end, 1000, f"{yrs}yr")

print("\n=== Limit sweep: 2yr window, end=2026-06-19 ===")
end = datetime(2026, 6, 19, tzinfo=timezone.utc)
start = end - timedelta(days=730)
for lim in (100, 250, 500, 1000):
    try_pull("AAPL", start, end, lim, f"limit={lim}")

print("\n=== Cross-symbol at end=2026-06-19, 2yr, limit=1000 ===")
end = datetime(2026, 6, 19, tzinfo=timezone.utc)
start = end - timedelta(days=730)
for sym in ("AAPL", "NVDA", "MU", "AVGO", "AMAT", "COIN", "SPY", "QQQ", "SMH"):
    try_pull(sym, start, end, 1000, sym)
