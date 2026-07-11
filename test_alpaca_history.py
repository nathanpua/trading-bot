"""Test how many daily bars Alpaca will actually return for the paper account."""
import os
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from datetime import datetime, timedelta, timezone

# Load keys from .env
key, sec = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
env_path = os.path.join(os.path.dirname(__file__), ".env")
for line in open(env_path):
    line = line.strip()
    if line.startswith("ALPACA_API_KEY=") and not line.startswith("#"):
        key = line.split("=", 1)[1].strip().strip("'\"")
    elif line.startswith("ALPACA_SECRET_KEY=") and not line.startswith("#"):
        sec = line.split("=", 1)[1].strip().strip("'\"")
print("keys loaded:", bool(key), bool(sec))

client = StockHistoricalDataClient(api_key=key, secret_key=sec)

end = datetime.now(timezone.utc)
start_2y = end - timedelta(days=730)
start_1y = end - timedelta(days=365)

print("=== Test 1: limit=500, no dates ===")
try:
    req = StockBarsRequest(
        symbol_or_symbols="AAPL",
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        limit=500,
    )
    df = client.get_stock_bars(req).df
    print(f"rows={len(df)}")
    if len(df):
        print(df.head(2)[["open", "high", "low", "close", "volume"]])
        print(df.tail(2)[["open", "high", "low", "close", "volume"]])
except Exception as e:
    import traceback
    traceback.print_exc()

print("\n=== Test 2: start/end 2yr, limit=1000 ===")
try:
    req = StockBarsRequest(
        symbol_or_symbols="AAPL",
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=start_2y,
        end=end,
        limit=1000,
    )
    df = client.get_stock_bars(req).df
    print(f"rows={len(df)}")
    if len(df):
        ts = df.index.get_level_values("timestamp") if "timestamp" in df.index.names else df.index
        print(f"range: {ts.min()} -> {ts.max()}")
        print(df.head(2)[["open", "high", "low", "close", "volume"]])
except Exception as e:
    import traceback
    traceback.print_exc()

print("\n=== Test 3: start/end 1yr only ===")
try:
    req = StockBarsRequest(
        symbol_or_symbols="AAPL",
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=start_1y,
        end=end,
        limit=500,
    )
    df = client.get_stock_bars(req).df
    print(f"rows={len(df)}")
except Exception as e:
    print("ERROR:", repr(e)[:300])

print("\n=== Test 4: a second symbol NVDA, 2yr ===")
try:
    req = StockBarsRequest(
        symbol_or_symbols="NVDA",
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=start_2y,
        end=end,
        limit=1000,
    )
    df = client.get_stock_bars(req).df
    print(f"rows={len(df)}")
    if len(df):
        ts = df.index.get_level_values("timestamp") if "timestamp" in df.index.names else df.index
        print(f"range: {ts.min()} -> {ts.max()}")
except Exception as e:
    print("ERROR:", repr(e)[:300])
