"""
Finnhub data client — drop-in replacement for alpaca_client.get_bars() and
get_quote(), using the Finnhub REST API.

Why: Alpha Vantage's free tier (25 req/day) is far too tight for scanning a
broad universe of symbols. Finnhub's free tier allows ~60 req/min and richer
history, so it is now the primary market-data feed for this bot.

Public API (compatible with indicators.py):
    get_quote(symbol) -> dict          {c, d, dp, h, l, o, pc, t}
    get_bars(symbol, timeframe, limit) -> DataFrame[timestamp,open,high,low,close,volume]

All other modules (indicators.add_all_indicators, generate_signals) consume
the DataFrame unchanged because the column names match alpaca_client.
"""

import os
import time
import pathlib
import requests
import pandas as pd

_BASE = "https://finnhub.io/api/v1"
_HERE = pathlib.Path(__file__).resolve().parent
_DATA_DIR = _HERE / "data"
_ENV_PATH = _HERE / ".env"

# Finnhub candle resolution codes
_RESOLUTION = {
    "1Min": "1",
    "5Min": "5",
    "15Min": "15",
    "30Min": "30",
    "1Hour": "60",
    "1Day": "D",
    "1Week": "W",
    "1Month": "M",
}

_session = requests.Session()
_last_call = 0.0
_MIN_INTERVAL = 0.4  # ~150 req/min ceiling, well under the 60/min free limit when shared


def _load_key():
    """Read FINNHUB_API_KEY from ~/trading-bot/.env (no dotenv dependency)."""
    if os.environ.get("FINNHUB_API_KEY"):
        return os.environ["FINNHUB_API_KEY"]
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("FINNHUB_API_KEY=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    os.environ["FINNHUB_API_KEY"] = val
                    return val
    raise RuntimeError("FINNHUB_API_KEY not set in env or ~/trading-bot/.env")


def _throttle():
    global _last_call
    dt = time.time() - _last_call
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last_call = time.time()


def _get(path, params, timeout=20):
    params = dict(params)
    params["token"] = _load_key()
    _throttle()
    r = _session.get(_BASE + path, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_quote(symbol):
    """Real-time quote. Returns dict with c(current), h, l, o, pc(prev close),
    d(change), dp(change%), t."""
    return _get("/quote", {"symbol": symbol.upper()})


def get_bars(symbol, timeframe="1Day", limit=100, start=None, end=None):
    """Historical OHLCV bars as a DataFrame.

    Columns: timestamp, open, high, low, close, volume  (lowercase, matching
    alpaca_client.get_bars so indicators.py works unchanged).

    A local cache at ~/trading-bot/data/<symbol>_<tf>.csv is used to avoid
    re-fetching within the same calendar day (Finnhub daily candles are final
    after market close).
    """
    symbol = symbol.upper()
    res = _RESOLUTION.get(timeframe)
    if res is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    _DATA_DIR.mkdir(exist_ok=True)
    cache = _DATA_DIR / f"{symbol}_{res}.csv"
    today = pd.Timestamp.utcnow().strftime("%Y-%m-%d")

    # Serve from cache if it exists and is from today (daily/weekly only)
    if res in ("D", "W", "M") and cache.exists():
        try:
            cached = pd.read_csv(cache)
            if not cached.empty:
                last_ts = pd.to_datetime(cached["timestamp"].iloc[-1])
                if last_ts.strftime("%Y-%m-%d") >= today:
                    return cached.copy()
        except Exception:
            pass

    now = int(time.time())
    if end is not None:
        to_ts = int(pd.Timestamp(end).timestamp()) if not isinstance(end, int) else end
    else:
        to_ts = now
    # Over-request calendar days so ~`limit` trading days survive weekends/holidays
    lookback_days = max(int(limit * 1.8) + 10, 60)
    if start is not None:
        from_ts = int(pd.Timestamp(start).timestamp()) if not isinstance(start, int) else start
    else:
        from_ts = to_ts - lookback_days * 86400

    try:
        data = _get("/stock/candle", {
            "symbol": symbol,
            "resolution": res,
            "from": from_ts,
            "to": to_ts,
        })
    except Exception as e:
        # Cache fallback if the network/API errors
        if cache.exists():
            return pd.read_csv(cache).copy()
        raise

    status = data.get("s") if isinstance(data, dict) else None
    if status != "ok" or not data.get("c"):
        # Finnhub returns {'s':'no_data'} when the symbol/resolution is gated
        if cache.exists():
            return pd.read_csv(cache).copy()
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(data["t"], unit="s", utc=True).tz_convert("US/Eastern").strftime("%Y-%m-%d"),
        "open": data["o"],
        "high": data["h"],
        "low": data["l"],
        "close": data["c"],
        "volume": data["v"],
    })
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    if limit and len(df) > limit:
        df = df.tail(limit).reset_index(drop=True)

    # Persist cache (daily/weekly only)
    if res in ("D", "W", "M"):
        try:
            df.to_csv(cache, index=False)
        except Exception:
            pass
    return df


def get_bars_multi(symbols, timeframe="1Day", limit=100):
    """Fetch bars for many symbols with throttling. Returns {symbol: DataFrame}."""
    out = {}
    for s in symbols:
        try:
            out[s] = get_bars(s, timeframe=timeframe, limit=limit)
        except Exception as e:
            out[s] = None
    return out


# ───────────────────────── news ─────────────────────────
# Finnhub free tier includes /news (market) and /company-news (per-symbol).
# These are the bot's PRIMARY news source — they work reliably via terminal,
# unlike web_search which has no backend configured on this profile.

def get_market_news(category="general", count=50):
    """Latest market news headlines from Finnhub free tier.

    Returns list of dicts: headline, summary, source, url, related, datetime(unix),
    category, id. ``category`` can be 'general', 'forex', 'crypto', 'merger'.
    """
    data = _get("/news", {"category": category})
    if isinstance(data, list):
        return data[:count]
    return []


def get_company_news(symbol, days=7, count=30):
    """Company-specific news for ``symbol`` over the last ``days`` days.

    Returns list of dicts: headline, summary, source, url, related, datetime(unix),
    id, category, image.
    """
    from datetime import datetime, timedelta
    symbol = symbol.upper()
    today = datetime.utcnow()
    frm = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    to = today.strftime("%Y-%m-%d")
    data = _get("/company-news", {"symbol": symbol, "from": frm, "to": to})
    if isinstance(data, list):
        return data[:count]
    return []


if __name__ == "__main__":
    # Smoke test
    import json
    print("== QUOTE MU ==")
    print(json.dumps(get_quote("MU"), indent=2))
    df = get_bars("MU", "1Day", 100)
    print(f"== BARS MU: {len(df)} rows ==")
    print(df[["timestamp", "close", "volume"]].tail().to_string(index=False) if not df.empty else "EMPTY")
