"""
Alpaca API client wrapper for the trading bot.

Handles authentication, provides convenience methods for account info,
market data, order execution, and position management.

Requires ALPACA_API_KEY and ALPACA_SECRET_KEY in environment or .env.
Uses paper trading by default (https://paper-api.alpaca.markets).
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockQuotesRequest, StockTradesRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        MarketOrderRequest,
        LimitOrderRequest,
        StopLossRequest,
        StopOrderRequest,
        GetOrdersRequest,
    )
    from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
except ImportError:
    print("ERROR: alpaca-py not installed. Run: pip install alpaca-py", file=sys.stderr)
    sys.exit(1)

# Paper trading endpoint by default
PAPER_URL = "https://paper-api.alpaca.markets"


def _get_keys():
    """Load API keys from env or .env file."""
    key = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        # Try loading from .env in workspace
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ALPACA_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip("'\"")
                    elif line.startswith("ALPACA_SECRET_KEY="):
                        secret = line.split("=", 1)[1].strip().strip("'\"")
    if not key or not secret:
        print(
            "ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY in environment or "
            "~/trading-bot/.env\n"
            "Get free paper trading keys at: https://app.alpaca.markets/paper/dashboard/overview",
            file=sys.stderr,
        )
        sys.exit(1)
    return key, secret


def get_trading_client() -> TradingClient:
    """Get an authenticated Alpaca trading client (paper trading)."""
    key, secret = _get_keys()
    return TradingClient(api_key=key, secret_key=secret, paper=True)


def get_data_client() -> StockHistoricalDataClient:
    """Get an authenticated Alpaca market data client."""
    key, secret = _get_keys()
    return StockHistoricalDataClient(api_key=key, secret_key=secret)


def get_account():
    """Get account details: buying power, portfolio value, P&L."""
    client = get_trading_client()
    acct = client.get_account()
    equity = float(acct.equity)
    last_equity = float(acct.last_equity)
    day_pl = equity - last_equity
    day_plpc = (day_pl / last_equity) if last_equity else 0
    return {
        "id": str(acct.id),
        "equity": str(acct.equity),
        "cash": str(acct.cash),
        "buying_power": str(acct.buying_power),
        "portfolio_value": str(acct.portfolio_value),
        "last_equity": str(acct.last_equity),
        "day_trade_count": acct.daytrade_count,
        "pattern_day_trader": acct.pattern_day_trader,
        "trading_blocked": acct.trading_blocked,
        "trade_suspended_by_user": acct.trade_suspended_by_user,
        "shorting_enabled": acct.shorting_enabled,
        "multiplier": str(acct.multiplier),
        "day_pl": str(round(day_pl, 2)),
        "day_plpc": str(round(day_plpc, 4)),
        "long_market_value": str(acct.long_market_value),
        "status": acct.status,
    }


def get_positions():
    """Get all open positions."""
    client = get_trading_client()
    positions = client.get_all_positions()
    result = []
    for p in positions:
        result.append({
            "symbol": p.symbol,
            "qty": str(p.qty),
            "side": p.side,
            "market_value": str(p.market_value),
            "cost_basis": str(p.cost_basis),
            "unrealized_pl": str(p.unrealized_pl),
            "unrealized_plpc": str(p.unrealized_plpc),
            "current_price": str(p.current_price),
            "avg_entry_price": str(p.avg_entry_price),
            "change_today": str(p.change_today),
        })
    return result


def _fetch_alpaca_bars(symbol, timeframe="1Day", limit=1000, start=None, end=None):
    """
    Fetch historical OHLCV bars directly from Alpaca (richest free-tier source).

    The paper/free tier blocks querying *recent* (same-day) SIP data with a 403
    "subscription does not permit querying recent SIP data". Completed daily
    sessions are allowed, so when no `end` is supplied we set end = now - 1 day.

    When no `start` is supplied, a ~3.5yr window is used. This keeps the number
    of bars in the window (~890) at or below the default `limit` (1000) so Alpaca
    returns the MOST RECENT history (a wider window would return the oldest
    `limit` bars and drop the recent ones).

    Returns DataFrame(timestamp, open, high, low, close, volume) sorted ascending,
    or None on failure.
    """
    import pandas as pd
    from datetime import datetime, timedelta, timezone
    try:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        tf_map = {
            "1Min": TimeFrame(1, TimeFrameUnit.Minute),
            "5Min": TimeFrame(5, TimeFrameUnit.Minute),
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
            "1Day": TimeFrame(1, TimeFrameUnit.Day),
        }
        tf = tf_map.get(timeframe, TimeFrame(1, TimeFrameUnit.Day))
        now = datetime.now(timezone.utc)
        if end is None:
            end = now - timedelta(days=1)  # SIP-safe: avoid the current-day bar
        if start is None:
            start = end - timedelta(days=1300)  # ~3.5yr -> ~890 daily bars
        client = get_data_client()
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            end=end,
            limit=limit,
        )
        df = client.get_stock_bars(req).df
        if df is None or df.empty:
            return None
        # Flatten Alpaca's (symbol, timestamp) MultiIndex into plain columns.
        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()
        else:
            idx_name = df.index.name or "index"
            df = df.reset_index().rename(columns={idx_name: "timestamp"})
        df = df.rename(columns=str.lower)
        if timeframe == "1Day":
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None).dt.normalize()
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        keep = ["timestamp", "open", "high", "low", "close", "volume"]
        df = df[[c for c in keep if c in df.columns]]
        df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
        return df
    except Exception:
        return None


def get_bars(symbols, timeframe="1Day", limit=100, start=None, end=None):
    """
    Get historical OHLCV bars.

    Primary source: LSE (London Strategic Edge) — free, deep history, fast.
    Fallback: Alpaca bars, then Alpha Vantage (legacy).

    Args:
        symbols: str or list of ticker symbols
        timeframe: '1Min', '5Min', '15Min', '1Hour', '1Day' (default '1Day')
        limit: number of bars (default 100)
        start/end: ISO datetime (optional)
    Returns pandas DataFrame: timestamp, open, high, low, close, volume, symbol.
    """
    import pandas as pd
    from datetime import datetime, timedelta

    if isinstance(symbols, str):
        symbols = [symbols]

    all_dfs = []
    for sym in symbols:
        # Primary: LSE
        try:
            import lse_client
            df = lse_client.get_bars(sym, timeframe=timeframe, limit=limit)
            if df is not None and not df.empty:
                if len(df) >= 2:  # LSE data is valid
                    df["symbol"] = sym
                    all_dfs.append(df.tail(limit))
                    continue
        except Exception:
            pass  # Fall through to Alpaca

        # Fallback: Alpaca bars (legacy path)
        alp_df = _fetch_alpaca_bars(sym, timeframe=timeframe, start=start, end=end)
        if alp_df is not None and not alp_df.empty:
            df = alp_df
            df["symbol"] = sym
            all_dfs.append(df.tail(limit))
            continue

        # Last resort: Alpha Vantage
        av_df = _fetch_alphavantage(sym)
        if av_df is not None and not av_df.empty:
            av_df["symbol"] = sym
            all_dfs.append(av_df.tail(limit))

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True)


def _fetch_alphavantage(symbol):
    """Fetch daily bars from Alpha Vantage free API. Returns DataFrame or None."""
    import urllib.request
    import io

    # Load key from .env if not in environment
    api_key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not api_key:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ALPHAVANTAGE_API_KEY=") and not line.startswith("#"):
                        api_key = line.split("=", 1)[1].strip().strip("'\"")
    url = (
        f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY"
        f"&symbol={symbol}&apikey={api_key}&datatype=csv&outputsize=compact"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        import pandas as pd
        df = pd.read_csv(io.BytesIO(resp.read()))
        if "timestamp" in df.columns and len(df) > 0:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df.sort_values("timestamp").reset_index(drop=True)
    except Exception:
        pass
    return None


def _fetch_alpaca_snapshot_bars(symbol):
    """Get today + previous day bar from Alpaca snapshot (free tier). Returns DataFrame."""
    try:
        from alpaca.data.requests import StockSnapshotRequest
        client = get_data_client()
        snap = client.get_stock_snapshot(StockSnapshotRequest(symbol_or_symbols=symbol))
        bars = []
        for sym, data in snap.items():
            for bar_attr in ("previous_daily_bar", "daily_bar"):
                bar = getattr(data, bar_attr, None)
                if bar:
                    bars.append({
                        "timestamp": bar.timestamp,
                        "open": float(bar.open),
                        "high": float(bar.high),
                        "low": float(bar.low),
                        "close": float(bar.close),
                        "volume": float(bar.volume),
                    })
        if bars:
            import pandas as pd
            df = pd.DataFrame(bars)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    except Exception:
        pass
    return None


def place_market_order(symbol, qty, side="buy"):
    """
    Place a market order.
    
    Args:
        symbol: ticker symbol (e.g. 'AAPL')
        qty: number of shares (int or float for fractional)
        side: 'buy' or 'sell'
    """
    client = get_trading_client()
    order = MarketOrderRequest(
        symbol=symbol.upper(),
        qty=qty,
        side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    result = client.submit_order(order)
    return {"id": str(result.id), "status": str(result.status), "symbol": result.symbol,
            "qty": str(result.qty), "side": str(result.side), "type": str(result.order_type)}


def place_limit_order(symbol, qty, side, limit_price):
    """Place a limit order."""
    client = get_trading_client()
    order = LimitOrderRequest(
        symbol=symbol.upper(),
        qty=qty,
        side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        limit_price=limit_price,
    )
    result = client.submit_order(order)
    return {"id": str(result.id), "status": str(result.status), "symbol": result.symbol,
            "qty": str(result.qty), "limit_price": str(result.limit_price)}


def close_position(symbol):
    """Close a position entirely."""
    client = get_trading_client()
    client.close_position(symbol.upper())
    return {"symbol": symbol.upper(), "action": "closed"}


def cancel_order(order_id):
    """Cancel an open order by id."""
    client = get_trading_client()
    client.cancel_order_by_id(order_id)
    return {"order_id": str(order_id), "action": "cancelled"}


def place_stop_order(symbol, qty, stop_price, side="sell"):
    """Place a stop (stop-loss) order. Used for trailing-stop management."""
    client = get_trading_client()
    order = StopOrderRequest(
        symbol=symbol.upper(),
        qty=qty,
        side=OrderSide.SELL if side.lower() == "sell" else OrderSide.BUY,
        stop_price=Decimal(str(stop_price)),
        time_in_force=TimeInForce.GTC,
    )
    result = client.submit_order(order)
    return {"id": str(result.id), "status": str(result.status),
            "symbol": result.symbol, "qty": str(result.qty),
            "stop_price": str(stop_price)}


def get_open_orders_for_symbol(symbol):
    """Return open orders (stop/limit legs) attached to a symbol."""
    for o in get_orders(status="open", limit=100):
        if o.get("symbol", "").upper() == symbol.upper():
            yield o


def get_orders(status="open", limit=50):
    """Get orders by status ('open', 'closed', 'all')."""
    client = get_trading_client()
    status_map = {
        "open": QueryOrderStatus.OPEN,
        "closed": QueryOrderStatus.CLOSED,
        "all": QueryOrderStatus.ALL,
    }
    params = GetOrdersRequest(status=status_map.get(status, QueryOrderStatus.OPEN), limit=limit)
    orders = client.get_orders(params)
    result = []
    for o in orders:
        result.append({
            "id": str(o.id),
            "symbol": o.symbol,
            "side": str(o.side),
            "qty": str(o.qty),
            "status": str(o.status),
            "type": str(o.order_type),
            "created_at": str(o.created_at),
            "filled_price": str(o.filled_avg_price) if o.filled_avg_price else None,
            "filled_qty": str(o.filled_qty) if o.filled_qty else None,
        })
    return result


def is_market_open():
    """Check if US market is currently open."""
    client = get_trading_client()
    clock = client.get_clock()
    return {
        "is_open": clock.is_open,
        "next_open": str(clock.next_open),
        "next_close": str(clock.next_close),
        "timestamp": str(clock.timestamp),
    }
