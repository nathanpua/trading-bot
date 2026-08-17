"""
Volume-weighted momentum strategy.

Combines OBV (On-Balance Volume) trend with price momentum and
volume-weighted average price deviation.
"""

import numpy as np
import pandas as pd
from strategy_framework import delta, ts_mean

STRATEGY_META = {
    "id": "volume_weighted",
    "name": "Volume-Weighted Momentum",
    "theme": "volume",
    "description": "OBV trend + volume-weighted price deviation from VWAP",
    "columns_required": ["open", "high", "low", "close", "volume"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    volume = df["volume"]
    open_ = df["open"]
    high = df["high"]
    low = df["low"]

    # OBV (On-Balance Volume)
    direction = np.sign(close.diff().fillna(0))
    obv = (direction * volume).cumsum()
    obv_trend = delta(obv, 10) / (volume.rolling(10, min_periods=5).mean() * 10 + 1)
    obv_score = np.tanh(obv_trend.fillna(0))

    # Typical price VWAP
    vwap = (high + low + close) / 3.0
    vol_sum = volume.rolling(20, min_periods=10).sum()
    weighted = (vwap * volume).rolling(20, min_periods=10).sum()
    rolling_vwap = weighted / vol_sum.replace(0, np.nan)

    # Price vs rolling VWAP
    price_dev = (close - rolling_vwap) / rolling_vwap.replace(0, np.nan)
    price_dev_score = np.tanh(price_dev.fillna(0) * 5)

    # Volume momentum (is volume increasing?)
    vol_sma = ts_mean(volume, 10)
    vol_ratio = volume / vol_sma.replace(0, np.nan)
    vol_momentum = np.tanh((vol_ratio - 1).fillna(0) * 3)

    # Composite
    score = 0.4 * obv_score + 0.35 * price_dev_score + 0.25 * vol_momentum

    return score
