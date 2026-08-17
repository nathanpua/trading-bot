"""
Mean reversion strategy — RSI oversold/overbought + Bollinger position.

Combines RSI extremes with Bollinger Band position for reversal signals.
"""

import numpy as np
import pandas as pd

STRATEGY_META = {
    "id": "mean_reversion",
    "name": "RSI + Bollinger Reversion",
    "theme": "reversal",
    "description": "RSI < 30 (oversold bounce) or RSI > 70 (overbought reversal) confirmed by Bollinger position",
    "columns_required": ["high", "low", "close"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # RSI 14
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14, min_periods=10).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=10).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # Bollinger Bands
    sma = close.rolling(20, min_periods=10).mean()
    std = close.rolling(20, min_periods=10).std()
    upper = sma + 2 * std
    lower = sma - 2 * std

    # BB position: 0 = at lower band, 1 = at upper band
    bb_width = (upper - lower).replace(0, np.nan)
    bb_pos = (close - lower) / bb_width

    # Reversion score:
    # Oversold (RSI < 30, BB < 0.1) → positive (buy the bounce)
    # Overbought (RSI > 70, BB > 0.9) → negative (sell the reversal)
    score = pd.Series(0.0, index=close.index)

    # Oversold conditions → bullish reversal
    oversold = (rsi < 35) & (bb_pos < 0.2)
    score = score.where(~oversold, (40 - rsi) / 40)  # stronger as RSI drops

    # Overbought conditions → bearish reversal
    overbought = (rsi > 65) & (bb_pos > 0.8)
    score = score.where(~overbought, -(rsi - 60) / 40)

    return score
