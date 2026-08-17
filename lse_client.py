"""
LSE (London Strategic Edge) data client — primary market data feed.

Replaces Finnhub for OHLCV bars and real-time quotes. Uses:
  - REST candles() for historical daily bars (back to 2003)
  - REST candles() with 1m timeframe for real-time quotes
  - WebSocket stream for live tick prices (bid/ask/volume)
  - REST economic_calendar() for macro events

Finnhub is retained ONLY for news (get_market_news, get_company_news).

Public API (drop-in compatible with finnhub_client/alpaca_client patterns):
    get_quote(symbol) -> dict          {c, d, dp, h, l, o, pc, t}
    get_bars(symbol, timeframe, limit) -> DataFrame[timestamp,open,high,low,close,volume]
    get_bars_multi(symbols, ...)       -> {symbol: DataFrame}
    get_economic_calendar(region, start, end) -> list[dict]

All other modules (indicators.add_all_indicators, generate_signals) consume
the DataFrame unchanged because column names match alpaca_client.
"""

import os
import time
import pathlib
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

_HERE = pathlib.Path(__file__).resolve().parent
_DATA_DIR = _HERE / "data"
_ENV_PATH = _HERE / ".env"

_session = requests.Session()
_last_call = 0.0
_MIN_INTERVAL = 0.05  # 200 calls/min ceiling (LSE free tier limit)

# LSE timeframe mapping (LSE uses different codes than Finnhub/Alpaca)
_TIMEFRAME_MAP = {
    "1Min": "1m", "5Min": "5m", "15Min": "15m", "30Min": "30m",
    "1Hour": "1h", "1Day": "1d", "1Week": "1w", "1Month": "1mo",
}

# WebSocket tick buffer: symbol -> list of recent ticks
_ws_ticks: dict[str, list[dict]] = defaultdict(list)
_ws_connected = False
_ws_symbols: set[str] = set()
_MAX_TICK_BUFFER = 500  # per symbol


def _load_key():
    """Read LSE_API_KEY from env or ~/trading-bot/.env (no dotenv dependency)."""
    if os.environ.get("LSE_API_KEY"):
        return os.environ["LSE_API_KEY"]
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("LSE_API_KEY=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    os.environ["LSE_API_KEY"] = val
                    return val
    raise RuntimeError("LSE_API_KEY not set in env or ~/trading-bot/.env")


def _throttle():
    global _last_call
    dt = time.time() - _last_call
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last_call = time.time()


def _get_rest(path, params, timeout=20):
    """REST GET to LSE vault API."""
    key = _load_key()
    _throttle()
    headers = {"x-api-key": key}
    url = f"https://api.londonstrategicedge.com/vault/{path}"
    r = _session.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ───────────────────────── quotes ─────────────────────────


def get_quote(symbol):
    """Real-time quote via latest 1-minute candle.

    Returns dict compatible with Finnhub's /quote format:
        {c: current, h: high, l: low, o: open, pc: prev_close, t: timestamp}
    """
    symbol = symbol.upper()

    # Try WebSocket buffer first for freshest price
    if _ws_connected and symbol in _ws_ticks and _ws_ticks[symbol]:
        latest = _ws_ticks[symbol][-1]
        price = latest["price"]
        prev_close = _get_prev_close(symbol)
        change = price - prev_close if prev_close else 0
        return {
            "c": round(price, 2),
            "h": round(latest.get("ask", price), 2),
            "l": round(latest.get("bid", price), 2),
            "o": price,  # approximated
            "pc": round(prev_close, 2) if prev_close else price,
            "d": round(change, 2),
            "dp": round(change / prev_close * 100, 2) if prev_close else 0,
            "t": int(time.time()),
        }

    # Fallback: daily candle close (works during and after market hours).
    # Use order=desc to get most recent data.
    try:
        data = _get_rest("candles", {
            "symbol": symbol, "timeframe": "1d", "limit": 3, "order": "desc",
        })
        if isinstance(data, list) and len(data) >= 2:
            # order=desc: data[0] = today/most recent, data[1] = previous day
            curr = data[0]
            prev = data[1]
            prev_close = prev["close"]
            price = curr["close"]
            change = price - prev_close
            return {
                "c": round(price, 2),
                "h": round(curr.get("high", price), 2),
                "l": round(curr.get("low", price), 2),
                "o": round(curr.get("open", price), 2),
                "pc": round(prev_close, 2),
                "d": round(change, 2),
                "dp": round(change / prev_close * 100, 2) if prev_close else 0,
                "t": int(time.time()),
            }
    except Exception as e:
        logger.warning("LSE quote fallback failed for %s: %s", symbol, e)

    raise RuntimeError(f"LSE quote unavailable for {symbol}")


_prev_close_cache: dict[str, tuple[float, float]] = {}


def _get_prev_close(symbol):
    """Get previous day's close, cached for 1 hour."""
    symbol = symbol.upper()
    now = time.time()
    cached = _prev_close_cache.get(symbol)
    if cached and now - cached[0] < 3600:
        return cached[1]
    try:
        data = _get_rest("candles", {
            "symbol": symbol, "timeframe": "1d", "limit": 3, "order": "desc",
        })
        if isinstance(data, list) and len(data) >= 2:
            # order=desc: data[0] = most recent, data[1] = previous
            prev_close = data[1]["close"]
            _prev_close_cache[symbol] = (now, prev_close)
            return prev_close
        elif isinstance(data, list) and len(data) == 1:
            prev_close = data[0]["close"]
            _prev_close_cache[symbol] = (now, prev_close)
            return prev_close
    except Exception as e:
        logger.debug("prev_close fetch failed for %s: %s", symbol, e)
    return None


# ───────────────────────── bars / candles ─────────────────────────


def get_bars(symbol, timeframe="1Day", limit=100, start=None, end=None):
    """Historical OHLCV bars as a DataFrame.

    Columns: timestamp, open, high, low, close, volume
    (lowercase, matching alpaca_client.get_bars so indicators.py works unchanged).

    A local cache at ~/trading-bot/data/<symbol>_<tf>.csv is used to avoid
    re-fetching within the same calendar day.
    """
    symbol = symbol.upper()
    tf = _TIMEFRAME_MAP.get(timeframe)
    if tf is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    _DATA_DIR.mkdir(exist_ok=True)
    cache = _DATA_DIR / f"{symbol}_{tf}.csv"
    today = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")

    # Serve from cache if fresh (daily/weekly only)
    if tf in ("1d", "1w", "1mo") and cache.exists():
        try:
            cached = pd.read_csv(cache)
            if not cached.empty:
                last_ts = pd.to_datetime(cached["timestamp"].iloc[-1])
                if last_ts.strftime("%Y-%m-%d") >= today:
                    if limit and len(cached) > limit:
                        return cached.tail(limit).reset_index(drop=True)
                    return cached.copy()
        except Exception:
            pass

    # Calculate date range — LSE REST default returns oldest-first from first available date.
    # We must use order=desc to get the most recent bars, then reverse for ascending order.
    if start is not None:
        start_str = str(start)[:10]
    else:
        lookback_days = max(int(limit * 1.8) + 10, 120)
        start_str = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    # Request with order=desc so we get the MOST RECENT data first
    fetch_limit = min(limit if limit else 5000, 5000)
    params = {"symbol": symbol, "timeframe": tf, "limit": fetch_limit,
              "start": start_str, "order": "desc"}

    try:
        data = _get_rest("candles", params)
    except Exception as e:
        # Cache fallback if the network/API errors
        logger.warning("LSE bars fetch failed for %s: %s", symbol, e)
        if cache.exists():
            return pd.read_csv(cache).copy()
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    if not isinstance(data, list) or not data:
        if cache.exists():
            return pd.read_csv(cache).copy()
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    # Build DataFrame — data comes in desc order (most recent first), reverse to ascending
    df = pd.DataFrame(data)
    df = df.iloc[::-1].reset_index(drop=True)  # reverse to ascending (oldest first)

    # Normalize column names (LSE REST returns 'ts' for timestamp)
    if "ts" in df.columns:
        df = df.rename(columns={"ts": "timestamp"})
    elif "timestamp" in df.columns:
        pass  # SDK uses 'timestamp'

    # Ensure all required columns exist
    for col in ["timestamp", "open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            df[col] = None

    df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()

    # Normalize timestamp format to YYYY-MM-DD for daily, ISO for intraday
    if tf == "1d":
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d")
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    # Clean up
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    if limit and len(df) > limit:
        df = df.tail(limit).reset_index(drop=True)

    # Persist cache (daily/weekly only)
    if tf in ("1d", "1w", "1mo"):
        try:
            df.to_csv(cache, index=False)
        except Exception:
            pass

    return df


def get_bars_multi(symbols, timeframe="1Day", limit=100):
    """Fetch bars for many symbols. Returns {symbol: DataFrame}."""
    out = {}
    for s in symbols:
        try:
            out[s] = get_bars(s, timeframe=timeframe, limit=limit)
        except Exception as e:
            logger.warning("get_bars_multi failed for %s: %s", s, e)
            out[s] = None
    return out


# ───────────────────────── WebSocket ─────────────────────────


def start_websocket(symbols, background=True):
    """Start WebSocket streams for live price ticks.

    LSE allows 16 symbols per connection. For 25 ETFs we use 2 connections.
    This runs in background daemon threads.

    Args:
        symbols: list of ticker symbols to stream
        background: if True, run in daemon threads (recommended)
    """
    import threading

    global _ws_connected, _ws_symbols

    symbols = [s.upper() for s in symbols]
    _ws_symbols.update(symbols)

    # Split into chunks of 16 (LSE WS limit per connection)
    chunks = [symbols[i:i + 16] for i in range(0, len(symbols), 16)]

    def _ws_worker(chunk):
        try:
            from lse import LSE
            key = _load_key()
            client = LSE(api_key=key)

            def on_tick(tick):
                buf = _ws_ticks[tick.symbol]
                buf.append({
                    "price": tick.price,
                    "bid": getattr(tick, "bid", None),
                    "ask": getattr(tick, "ask", None),
                    "volume": getattr(tick, "volume", None),
                    "ts": time.time(),
                })
                # Trim buffer
                if len(buf) > _MAX_TICK_BUFFER:
                    _ws_ticks[tick.symbol] = buf[-_MAX_TICK_BUFFER:]

            client.on("tick", on_tick)
            client.on("error", lambda e: logger.warning("LSE WS error: %s", e))

            client.connect(symbols=chunk)
            logger.info("LSE WebSocket connected for %d symbols", len(chunk))

        except Exception as e:
            logger.warning("LSE WebSocket failed for chunk %s: %s", chunk, e)

    if background:
        for chunk in chunks:
            t = threading.Thread(target=_ws_worker, args=(chunk,), daemon=True)
            t.start()
        _ws_connected = True
        logger.info("Started %d LSE WebSocket threads for %d symbols", len(chunks), len(symbols))
    else:
        for chunk in chunks:
            _ws_worker(chunk)

    return len(chunks)


def get_ws_price(symbol):
    """Get latest WebSocket tick price for a symbol, or None."""
    symbol = symbol.upper()
    buf = _ws_ticks.get(symbol, [])
    if buf:
        return buf[-1]["price"]
    return None


def is_ws_connected():
    """Check if WebSocket manager has been started."""
    return _ws_connected


# ───────────────────────── economic calendar ─────────────────────────


def get_economic_calendar(region="US", start=None, end=None):
    """Economic calendar events from LSE.

    Args:
        region: country code (US, UK, EU, etc.)
        start/end: ISO date strings (default: today, +7 days)

    Returns list of dicts with keys: date, event, importance, forecast, previous, etc.
    """
    if start is None:
        start = datetime.utcnow().strftime("%Y-%m-%d")
    if end is None:
        end = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        from lse import LSE
        key = _load_key()
        client = LSE(api_key=key)
        return client.economic_calendar(region=region, start=start, end=end)
    except Exception as e:
        logger.warning("LSE economic calendar failed: %s", e)
        return []


# ───────────────────────── usage / quota ─────────────────────────


def get_usage():
    """Check LSE API usage and quota."""
    try:
        key = _load_key()
        headers = {"x-api-key": key}
        r = _session.get(
            "https://api.londonstrategicedge.com/vault/usage",
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("LSE usage check failed: %s", e)
        return {}


if __name__ == "__main__":
    # Smoke test
    import json

    print("== LSE CLIENT SMOKE TEST ==\n")

    # Usage
    usage = get_usage()
    print("Usage:", json.dumps(usage, indent=2))

    # Quote
    print("\n== QUOTE SPY ==")
    q = get_quote("SPY")
    print(json.dumps(q, indent=2))

    # Bars
    print("\n== BARS SPY (1Day, 5 rows) ==")
    df = get_bars("SPY", "1Day", 5)
    print(df.to_string(index=False) if not df.empty else "EMPTY")

    # Multi bars
    print("\n== MULTI BARS (SPY, QQQ, GLD) ==")
    multi = get_bars_multi(["SPY", "QQQ", "GLD"], "1Day", 3)
    for sym, df2 in multi.items():
        if df2 is not None:
            print(f"  {sym}: {len(df2)} rows, last close={df2.iloc[-1]['close']}")
