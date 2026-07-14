"""
Volume-price divergence strategy.

Adapted from Qlib158 CORR10 and Kakushadze Alpha #6.
Positive price-volume correlation = healthy trend.
Negative correlation = divergence → reversal warning.
"""

import numpy as np
import pandas as pd
from strategy_framework import ts_corr, delta

STRATEGY_META = {
    "id": "volume_price",
    "name": "Volume-Price Divergence",
    "theme": "volume",
    "description": "Correlation of close vs log(volume) — divergence signals reversal risk",
    "columns_required": ["close", "volume"],
    "enabled": True,
}


def compute(df):
    close = df["close"]
    volume = df["volume"]

    # Log volume (handle zeros)
    log_vol = np.log1p(volume.clip(lower=0))

    # 10-day price-volume correlation
    corr_10 = ts_corr(close, log_vol, 10)

    # 5-day open-volume correlation (Alpha #6 variant)
    if "open" in df.columns:
        open_ = df["open"]
        corr_open_vol = ts_corr(open_, volume, 5)
        # Alpha #6: -1 * corr(open, volume, 10) — high open-volume neg corr = bullish
        alpha6 = -1.0 * ts_corr(open_, volume, 10)
    else:
        corr_open_vol = corr_10
        alpha6 = -corr_10

    # Volume trend (rising volume = conviction)
    vol_change = delta(log_vol, 5)

    # Composite: positive correlation + rising volume = bullish
    #            negative correlation (divergence) = bearish
    score = 0.5 * corr_10.fillna(0) + 0.3 * alpha6.fillna(0) + 0.2 * np.tanh(vol_change.fillna(0))

    return score
