"""
Momentum strategy — multi-horizon rate of change.

Adapted from Qlib158 ROC factors + Kakushadze Alpha #12.
Computes ROC at 5/10/20 day horizons, weighted toward recent.
"""

import numpy as np
import pandas as pd
from strategy_framework import safe_div, delta, ts_rank

STRATEGY_META = {
    "id": "momentum_roc",
    "name": "Multi-Horizon Momentum",
    "theme": "momentum",
    "description": "ROC(5) + ROC(10) + ROC(20) composite with trend confirmation",
    "columns_required": ["close"],
    "enabled": True,
}


def compute(df):
    close = df["close"]

    # Rate of change at 3 horizons
    roc_5 = safe_div(close, close.shift(5)) - 1.0
    roc_10 = safe_div(close, close.shift(10)) - 1.0
    roc_20 = safe_div(close, close.shift(20)) - 1.0

    # Weighted composite (recent matters more)
    composite = 0.5 * roc_5 + 0.3 * roc_10 + 0.2 * roc_20

    # Scale by volatility to avoid chasing noisy moves
    vol = close.pct_change().rolling(20, min_periods=10).std()
    vol = vol.replace(0, np.nan).fillna(0.02)

    # Risk-adjusted momentum score
    score = composite / (vol * 4)  # scale factor

    return score
