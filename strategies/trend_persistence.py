"""
Trend persistence strategy.

Uses ADX (trend strength) and directional movement to identify strong trends.
High ADX + price above SMA = strong uptrend (bullish).
Uses Qlib158 IMXD-style time-spread between highs and lows.
"""

import numpy as np
import pandas as pd
from strategy_framework import ts_argmax, ts_argmin, ts_mean

STRATEGY_META = {
    "id": "trend_persistence",
    "name": "ADX Trend Persistence",
    "theme": "momentum",
    "description": "ADX trend strength + SMA alignment + high-low timing spread",
    "columns_required": ["high", "low", "close"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Simple ADX proxy: directional movement ratio
    up_move = high.diff()
    down_move = -low.diff()
    dm_plus = (up_move > down_move) & (up_move > 0)
    dm_minus = (down_move > up_move) & (down_move > 0)
    atr = (high - low).rolling(14, min_periods=7).mean()
    di_plus = 100 * (up_move.where(dm_plus, 0).rolling(14, min_periods=7).mean() / atr.replace(0, np.nan))
    di_minus = 100 * (down_move.where(dm_minus, 0).rolling(14, min_periods=7).mean() / atr.replace(0, np.nan))
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx = dx.rolling(14, min_periods=7).mean()

    # SMA alignment
    sma_20 = ts_mean(close, 20)
    sma_50 = ts_mean(close, 50)
    above_sma = close > sma_20
    sma_aligned = (sma_20 > sma_50).astype(float)

    # Trend persistence: high-low timing (IMXD10 variant)
    argmax_h = ts_argmax(high, 10)
    argmin_l = ts_argmin(low, 10)
    spread = (argmax_h - argmin_l) / 10.0  # positive = high came after low (uptrend)

    # Composite score: strong ADX + above SMA + positive timing spread
    adx_score = np.tanh((adx - 25) / 10)  # sigmoid around ADX=25 (trend threshold)
    trend_dir = np.where(above_sma, 1.0, -0.5)  # being above SMA is bullish
    timing = np.tanh(spread.fillna(0))

    score = 0.4 * adx_score.fillna(0) * trend_dir + 0.3 * sma_aligned.fillna(0) + 0.3 * timing

    return pd.Series(score, index=close.index)
