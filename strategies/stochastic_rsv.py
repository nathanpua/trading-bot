"""
Stochastic position strategy — where does close sit in its recent range?

Adapted from Qlib158 RSV10 (raw stochastic value, KDJ indicator).
Unlike RSI (which uses average gain/loss magnitude), RSV uses the
absolute position within the high-low range. This makes it:
  - Faster to react at extremes (touches 0/1 before RSI hits 30/70)
  - Better for smooth-trending ETFs where RSI barely moves
  - Symmetric for long/short signals (no directional bias)

Score: (close - min(low,10)) / (max(high,10) - min(low,10))
Centered to [-0.5, +0.5]: values near +0.5 = at top of range (overbought),
values near -0.5 = at bottom (oversold → bullish for reversion).
"""

import numpy as np
import pandas as pd
from strategy_framework import ts_max, ts_min, safe_div

STRATEGY_META = {
    "id": "stochastic_rsv",
    "name": "Range Stochastic (KDJ)",
    "theme": "reversal",
    "description": "Price position in 10-day high-low range — overbought/oversold via KDJ RSV",
    "columns_required": ["high", "low", "close"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    high = df["high"]
    low = df["low"]

    hh = ts_max(high, 10)
    ll = ts_min(low, 10)
    rsv = safe_div(close - ll, hh - ll)

    # RSV is [0, 1] by definition. Center to [-0.5, +0.5].
    # Then invert: RSV near 0 (oversold) = bullish, RSV near 1 (overbought) = bearish.
    # This creates a mean-reversion signal from range position.
    return 0.5 - rsv
