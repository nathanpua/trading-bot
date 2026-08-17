"""
Down-day frequency strategy — fraction of down days in trailing window.

Adapted from Qlib158 CNTN10. Measures breadth/sentiment without using
price magnitude. A high ratio of down days = sustained selling pressure
which tends to exhaust and reverse. A low ratio = euphoria that fades.

This is orthogonal to momentum (which uses return magnitude) and
reversion (which uses price level). It captures BREADTH: how many days
are going down, regardless of how much.

Score: fraction of down days in 10 days, centered to [-0.5, +0.5].
High down-day ratio (>0.6) → oversold → bullish.
Low down-day ratio (<0.4) → overbought → bearish.
"""

import numpy as np
import pandas as pd

STRATEGY_META = {
    "id": "down_day_ratio",
    "name": "Down-Day Breadth",
    "theme": "breadth",
    "description": "Fraction of down days in 10 — sustained selling = contrarian buy",
    "columns_required": ["close"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    # 1 if down day, 0 if up/flat
    down = (close < close.shift(1)).astype("float64")
    # 10-day rolling mean of down indicator
    ratio = down.rolling(window=10, min_periods=10).mean()
    # Center: 0.5 is neutral. High ratio (>0.5) = oversold = bullish.
    return 0.5 - ratio
