"""
Technical analysis module — computes indicators and generates trading signals.

Uses the `ta` library for standard indicators (RSI, MACD, Bollinger Bands, etc.)
and pandas for data manipulation.

All functions accept a pandas DataFrame with at least: close, high, low, volume columns.
"""

import sys
import numpy as np
import pandas as pd

try:
    import ta
except ImportError:
    print("ERROR: ta library not installed. Run: pip install ta", file=sys.stderr)
    sys.exit(1)


def add_all_indicators(df):
    """Add a full suite of technical indicators to a OHLCV DataFrame."""
    df = df.copy()
    
    # RSI (14-period)
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    
    # MACD
    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_diff"] = macd.macd_diff()
    
    # Moving Averages
    df["sma_20"] = ta.trend.SMAIndicator(df["close"], window=20).sma_indicator()
    df["sma_50"] = ta.trend.SMAIndicator(df["close"], window=50).sma_indicator()
    df["ema_12"] = ta.trend.EMAIndicator(df["close"], window=12).ema_indicator()
    df["ema_26"] = ta.trend.EMAIndicator(df["close"], window=26).ema_indicator()
    
    # Bollinger Bands
    bb = ta.volatility.BollingerBands(df["close"])
    df["bb_high"] = bb.bollinger_hband()
    df["bb_low"] = bb.bollinger_lband()
    df["bb_mid"] = bb.bollinger_mavg()
    
    # ATR (volatility)
    df["atr"] = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range()
    
    # Stochastic Oscillator
    stoch = ta.momentum.StochasticOscillator(df["high"], df["low"], df["close"])
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()
    
    # ADX (trend strength)
    df["adx"] = ta.trend.ADXIndicator(df["high"], df["low"], df["close"]).adx()
    
    # Volume indicators
    df["obv"] = ta.volume.OnBalanceVolumeIndicator(df["close"], df["volume"]).on_balance_volume()
    
    return df


def generate_signals(df):
    """
    Generate buy/sell signals based on indicator confluence.
    Returns DataFrame with signal column: 1=buy, -1=sell, 0=hold.
    """
    df = add_all_indicators(df)
    df["signal"] = 0
    
    # RSI oversold/overbought
    rsi_buy = df["rsi"] < 30
    rsi_sell = df["rsi"] > 70
    
    # MACD crossover
    macd_buy = (df["macd"] > df["macd_signal"]) & (df["macd"].shift(1) <= df["macd_signal"].shift(1))
    macd_sell = (df["macd"] < df["macd_signal"]) & (df["macd"].shift(1) >= df["macd_signal"].shift(1))
    
    # SMA crossover (golden/death cross)
    sma_buy = (df["sma_20"] > df["sma_50"]) & (df["sma_20"].shift(1) <= df["sma_50"].shift(1))
    sma_sell = (df["sma_20"] < df["sma_50"]) & (df["sma_20"].shift(1) >= df["sma_50"].shift(1))
    
    # Bollinger Band breakout
    bb_buy = df["close"] < df["bb_low"]
    bb_sell = df["close"] > df["bb_high"]
    
    # Stochastic
    stoch_buy = (df["stoch_k"] < 20) & (df["stoch_k"] > df["stoch_d"])
    stoch_sell = (df["stoch_k"] > 80) & (df["stoch_k"] < df["stoch_d"])
    
    # Score-based signal: count how many indicators agree
    buy_score = rsi_buy.astype(int) + macd_buy.astype(int) + sma_buy.astype(int) + bb_buy.astype(int) + stoch_buy.astype(int)
    sell_score = rsi_sell.astype(int) + macd_sell.astype(int) + sma_sell.astype(int) + bb_sell.astype(int) + stoch_sell.astype(int)
    
    df.loc[buy_score >= 3, "signal"] = 1
    df.loc[sell_score >= 3, "signal"] = -1
    
    df["buy_score"] = buy_score
    df["sell_score"] = sell_score
    
    return df


def scan_watchlist(symbols, client_func=None):
    """
    Scan a list of symbols for current signals.
    Returns list of dicts with symbol, latest price, signal, and key indicators.
    """
    import alpaca_client
    
    results = []
    for sym in symbols:
        try:
            df = alpaca_client.get_bars(sym, timeframe="1Day", limit=100)
            if df.empty:
                continue
            df = generate_signals(df)
            latest = df.iloc[-1]
            
            results.append({
                "symbol": sym,
                "close": round(latest["close"], 2),
                "rsi": round(latest["rsi"], 1) if not np.isnan(latest["rsi"]) else None,
                "signal": int(latest["signal"]),
                "buy_score": int(latest["buy_score"]),
                "sell_score": int(latest["sell_score"]),
                "macd_diff": round(latest["macd_diff"], 4) if not np.isnan(latest["macd_diff"]) else None,
                "above_sma50": bool(latest["close"] > latest["sma_50"]) if not np.isnan(latest["sma_50"]) else None,
                "bb_position": "above_high" if latest["close"] > latest["bb_high"]
                              else "below_low" if latest["close"] < latest["bb_low"]
                              else "mid" if not np.isnan(latest["bb_mid"]) else None,
            })
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})
    
    return results


def format_scan_table(results):
    """Format scan results as a monospace table for Telegram."""
    lines = []
    lines.append("Symbol    Price     RSI    Signal  Score")
    lines.append("────────  ────────  ────   ──────  ─────")
    
    for r in sorted(results, key=lambda x: x.get("buy_score", 0), reverse=True):
        if "error" in r:
            lines.append(f"{r['symbol']:<8}  ERROR: {r['error'][:30]}")
            continue
        sig = "BUY" if r["signal"] == 1 else "SELL" if r["signal"] == -1 else "hold"
        rsi = f"{r['rsi']:.0f}" if r["rsi"] else "—"
        lines.append(
            f"{r['symbol']:<8}  {r['close']:>7.2f}  {rsi:>4}   {sig:>5}  {r['buy_score']}B/{r['sell_score']}S"
        )
    
    return "\n".join(lines)
