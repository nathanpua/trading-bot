"""
Return skewness strategy — negative of trailing 60-day return skewness.

Adapted from Harvey & Siddique (2000) conditional skewness factor.
ETFs with negatively-skewed returns (crash-prone: SOXL, TQQQ) tend to
earn risk premia. Positively-skewed (lottery-like) ETFs underperform.

Score: -skew(daily_returns, 60d), time-series ranked and centered.
Positive = negatively skewed (crash-prone, earns premium) → bullish.
Negative = positively skewed (lottery-like, overpriced) → bearish.
"""

import numpy as np
import pandas as pd
from strategy_framework import safe_div, ts_rank

STRATEGY_META = {
    "id": "return_skewness",
    "name": "Return Skewness",
    "theme": "volatility",
    "description": "Negative 60-day return skewness — tail-risk premium",
    "columns_required": ["close"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    daily_ret = safe_div(close - close.shift(1), close.shift(1))
    # 60-day rolling skewness
    skew = daily_ret.rolling(window=60, min_periods=30).skew()
    # Inverse: negative skew = bullish (risk premium)
    inv_skew = -skew
    # Normalize via time-series rank
    ranked = ts_rank(inv_skew, 60)
    return ranked - 0.5
