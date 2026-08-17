"""
Short-term reversion strategy — inverse trailing 21-day return.

Adapted from Jegadeesh (1990) academic short-term reversal factor.
ETFs mean-revert strongly at the monthly horizon because:
  - Authorized participants arb any premium/discount to NAV
  - Sector rotation creates overshoots that revert
  - Lower idiosyncratic risk = cleaner mean-reversion than stocks

Score: -return(21d), normalized via ts_rank to [0, 1] then centered to [-0.5, +0.5].
Positive score = recent loser → bullish (expected bounce).
Negative score = recent winner → bearish (expected fade).
"""

import numpy as np
import pandas as pd
from strategy_framework import delta, safe_div, ts_rank

STRATEGY_META = {
    "id": "short_reversion",
    "name": "21-Day Reversion",
    "theme": "reversal",
    "description": "Inverse 21-day return — recent losers bounce, recent winners fade",
    "columns_required": ["close"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    # 21-day return
    ret_21 = safe_div(delta(close, 21), close.shift(21))
    # Inverse: negative return = bullish for reversion
    inv_ret = -ret_21
    # Time-series rank: where does this inverse return sit relative to its own history?
    # Maps to [0, 1], center to [-0.5, +0.5]
    ranked = ts_rank(inv_ret, 60)
    return ranked - 0.5
