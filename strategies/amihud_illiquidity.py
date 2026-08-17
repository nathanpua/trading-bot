"""
Amihud illiquidity strategy — price impact per dollar of volume.

Adapted from Amihud (2002). Measures how much price moves per dollar
traded. High illiquidity = large price moves on low volume = less liquid
ETF (TSLL, ETHA, SOXS). Low illiquidity = tight pricing on high volume
(SPY, QQQ).

Less liquid ETFs carry a return premium. This strategy identifies
which ETFs are currently commanding that premium.

Score: 21-day average of |daily_return| / dollar_volume,
time-series ranked and centered to [-0.5, +0.5].
High illiquidity rank = premium opportunity → bullish.
"""

import numpy as np
import pandas as pd
from strategy_framework import safe_div, ts_mean, ts_rank

STRATEGY_META = {
    "id": "amihud_illiquidity",
    "name": "Amihud Illiquidity",
    "theme": "liquidity",
    "description": "Price impact per dollar volume — illiquidity premium signal",
    "columns_required": ["close", "volume"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    volume = df["volume"]
    daily_ret = safe_div(close - close.shift(1), close.shift(1))
    dollar_volume = close * volume
    # Amihud ILLIQ: |return| per dollar traded
    illiq = safe_div(daily_ret.abs(), dollar_volume)
    # 21-day average
    illiq_avg = ts_mean(illiq, 21)
    # Time-series rank to normalize across different ETFs
    ranked = ts_rank(illiq_avg, 60)
    # High rank = high illiquidity = premium opportunity
    return ranked - 0.5
