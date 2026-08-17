"""
Volatility regime strategy.

Uses realized vol relative to historical vol range to detect regime shifts.
Low vol vs history → risk-on (bullish).
High vol vs history → risk-off (bearish, defensive).
"""

import numpy as np
import pandas as pd
from strategy_framework import ts_mean, ts_std

STRATEGY_META = {
    "id": "volatility_regime",
    "name": "Volatility Regime",
    "theme": "volatility",
    "description": "Realized vol vs 60-day average — low vol = risk-on, high vol = risk-off",
    "columns_required": ["close"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    ret = close.pct_change()

    # Current realized vol (10-day)
    rv_10 = ts_std(ret, 10)

    # Long-term vol benchmark (60-day)
    rv_60 = ts_std(ret, 60)

    # Vol ratio: > 1 = elevated (bearish), < 1 = calm (bullish)
    vol_ratio = rv_10 / rv_60.replace(0, np.nan)

    # Invert and scale: low vol ratio → positive score
    score = -np.tanh((vol_ratio - 1.0) * 2)

    return score
