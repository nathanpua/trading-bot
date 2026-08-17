"""
Multi-factor composite strategy.

Combines signals from all other strategies into a single score.
This is a META-strategy that doesn't compute its own raw signals
but aggregates the outputs of the other 5 strategies.
"""

import numpy as np
import pandas as pd

STRATEGY_META = {
    "id": "multi_factor",
    "name": "Multi-Factor Composite",
    "theme": "composite",
    "description": "Equal-weight blend of momentum, reversion, vol-price, volatility, trend",
    "columns_required": ["open", "high", "low", "close", "volume"],
    "enabled": True,
}


def compute(df):
    from strategy_framework import get_registry

    reg = get_registry()
    other_ids = ["momentum_roc", "mean_reversion", "volume_price",
                 "volatility_regime", "trend_persistence", "volume_weighted"]

    scores = []
    for sid in other_ids:
        strat = reg.get(sid)
        if strat is None or not strat["enabled"]:
            continue
        try:
            raw = strat["compute_fn"](df)
            if isinstance(raw, pd.Series) and not raw.empty:
                val = float(raw.iloc[-1])
                if not np.isnan(val):
                    scores.append(np.tanh(val))
        except Exception:
            continue

    if not scores:
        return pd.Series(0.0, index=df.index)

    composite = sum(scores) / len(scores)
    return pd.Series(composite, index=df.index)
