"""Confirm a wide Alpaca window returns RECENT bars (not oldest) when window<=limit."""
from datetime import datetime, timedelta, timezone
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import alpaca_client

client = alpaca_client.get_data_client()
end = datetime.now(timezone.utc) - timedelta(days=1)

for days, lim in [(730, 1000), (1100, 1000), (1300, 1000), (1460, 1000)]:
    start = end - timedelta(days=days)
    req = StockBarsRequest(symbol_or_symbols="AAPL", timeframe=TimeFrame(1, TimeFrameUnit.Day),
                           start=start, end=end, limit=lim)
    df = client.get_stock_bars(req).df
    ts = df.index.get_level_values("timestamp")
    tag = "RECENT" if str(ts.max().date()) >= "2026-06-17" else "OLDEST-DROPPED"
    print(f"window={days}d limit={lim}: rows={len(df)}  {ts.min().date()} -> {ts.max().date()}  {tag}")
