"""
Strategy framework — pluggable alpha factor system.

Each strategy is a standalone module in strategies/ with:
  - STRATEGY_META dict (id, name, theme, description, columns_required)
  - compute(df) -> pd.Series  (signal score per row for a single symbol)

The engine builds a panel from live market data, runs all active strategies,
and produces a composite signal score per symbol.
"""

import os, sys, importlib, logging
from pathlib import Path
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
STRATEGIES_DIR = HERE / "strategies"


# ═══════════════════════════════════════════════════════════════
#  TIME-SERIES OPERATORS (adapted from Vibe-Trading base.py)
#  All operate on single-column Series within a per-symbol DataFrame.
# ═══════════════════════════════════════════════════════════════

def ts_rank(series, n):
    """Rolling percentile rank [0,1] of last value within n-window."""
    if n < 1:
        raise ValueError("ts_rank window must be >= 1")
    min_periods = min(n, 5)
    return series.rolling(n, min_periods=min_periods).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )


def ts_corr(x, y, n):
    """Rolling Pearson correlation, min_periods=n."""
    if n < 2:
        raise ValueError("ts_corr window must be >= 2")
    return x.rolling(n, min_periods=n).corr(y)


def ts_mean(series, n):
    """Rolling mean, warmup → NaN."""
    return series.rolling(n, min_periods=min(n, 5)).mean()


def ts_std(series, n):
    """Rolling sample std (ddof=1)."""
    return series.rolling(n, min_periods=min(max(n, 2), 10)).std(ddof=1)


def ts_max(series, n):
    """Rolling max."""
    return series.rolling(n, min_periods=min(n, 5)).max()


def ts_min(series, n):
    """Rolling min."""
    return series.rolling(n, min_periods=min(n, 5)).min()


def ts_argmax(series, n):
    """Rolling argmax (0-based index into window)."""
    return series.rolling(n, min_periods=min(n, 5)).apply(
        np.argmax, raw=True
    )


def ts_argmin(series, n):
    """Rolling argmin (0-based index into window)."""
    return series.rolling(n, min_periods=min(n, 5)).apply(
        np.argmin, raw=True
    )


def delta(series, d=1):
    """First difference at lag d (d >= 1)."""
    return series.diff(d)


def decay_linear(series, n):
    """Linear decay-weighted moving average (weights n, n-1, ..., 1)."""
    weights = np.arange(n, 0, -1, dtype=float)
    weights /= weights.sum()
    min_periods = min(n, 5)
    return series.rolling(n, min_periods=min_periods).apply(
        lambda x: np.dot(x, weights[:len(x)]) / weights[:len(x)].sum(), raw=True
    )


def signed_power(series, p):
    """sign(x) * |x|^p — preserves sign."""
    return np.sign(series) * np.abs(series) ** p


def safe_div(a, b):
    """Safe division: returns NaN where b == 0."""
    return a / b.replace(0, np.nan)


def returns(close):
    """Daily returns: close.pct_change()."""
    return close.pct_change()


def vwap(df):
    """Typical price VWAP: (H + L + C) / 3 (when true VWAP unavailable)."""
    return (df["high"] + df["low"] + df["close"]) / 3.0


# ═══════════════════════════════════════════════════════════════
#  STRATEGY REGISTRY
# ═══════════════════════════════════════════════════════════════

class StrategyRegistry:
    """Discovers, loads, and manages strategy modules."""

    def __init__(self):
        self._strategies = {}
        self._scan()

    def _scan(self):
        """Scan strategies/ dir for .py files with STRATEGY_META."""
        if not STRATEGIES_DIR.exists():
            logger.warning("strategies/ dir not found at %s", STRATEGIES_DIR)
            return

        for py_file in sorted(STRATEGIES_DIR.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                self._register(py_file)
            except Exception as e:
                logger.warning("Failed to register strategy %s: %s", py_file.name, e)

    def _register(self, py_file):
        """Load a strategy module and register it."""
        mod_name = f"strategies.{py_file.stem}"
        if mod_name not in sys.modules:
            spec = importlib.util.spec_from_file_location(mod_name, py_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)

        module = sys.modules[mod_name]

        # Require STRATEGY_META
        if not hasattr(module, "STRATEGY_META"):
            raise ValueError(f"{py_file.name}: missing STRATEGY_META")

        meta = module.STRATEGY_META
        if "id" not in meta:
            raise ValueError(f"{py_file.name}: STRATEGY_META missing 'id'")

        if not hasattr(module, "compute"):
            raise ValueError(f"{py_file.name}: missing compute() function")

        sid = meta["id"]
        self._strategies[sid] = {
            "id": sid,
            "name": meta.get("name", sid),
            "theme": meta.get("theme", "unknown"),
            "description": meta.get("description", ""),
            "columns_required": meta.get("columns_required", ["close"]),
            "enabled": meta.get("enabled", True),
            "module": module,
            "compute_fn": module.compute,
        }
        logger.info("Registered strategy: %s (%s)", sid, meta.get("name", sid))

    def list(self):
        """List all registered strategies."""
        return [
            {k: v for k, v in s.items() if k not in ("module", "compute_fn")}
            for s in self._strategies.values()
        ]

    def get(self, strategy_id):
        """Get a strategy by ID."""
        return self._strategies.get(strategy_id)

    def get_enabled(self):
        """Get all enabled strategies."""
        return [s for s in self._strategies.values() if s["enabled"]]

    def enable(self, strategy_id):
        """Enable a strategy."""
        if strategy_id in self._strategies:
            self._strategies[strategy_id]["enabled"] = True

    def disable(self, strategy_id):
        """Disable a strategy."""
        if strategy_id in self._strategies:
            self._strategies[strategy_id]["enabled"] = False

    def compute_all(self, df, active_ids=None):
        """Run all active strategies on a single-symbol OHLCV DataFrame.

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, volume
            active_ids: optional list of strategy IDs to run (default: all enabled)

        Returns:
            dict mapping strategy_id → {score, signal, detail}
        """
        results = {}
        strategies = self.get_enabled() if active_ids is None else [
            self._strategies[sid] for sid in active_ids
            if sid in self._strategies
        ]

        for strat in strategies:
            sid = strat["id"]
            try:
                # Check required columns
                required = strat["columns_required"]
                missing = [c for c in required if c not in df.columns]
                if missing:
                    results[sid] = {"score": 0, "signal": "neutral",
                                    "error": f"missing columns: {missing}"}
                    continue

                raw_score = strat["compute_fn"](df)

                # raw_score is a pd.Series — take the last value
                if isinstance(raw_score, pd.Series):
                    score_val = float(raw_score.iloc[-1]) if not raw_score.empty else 0.0
                    if np.isnan(score_val):
                        score_val = 0.0
                else:
                    score_val = float(raw_score) if raw_score is not None else 0.0
                    if np.isnan(score_val):
                        score_val = 0.0

                # Normalize to [-1, +1] range using tanh for stability
                normalized = float(np.tanh(score_val)) if score_val != 0 else 0.0

                if normalized > 0.15:
                    signal = "bullish"
                elif normalized < -0.15:
                    signal = "bearish"
                else:
                    signal = "neutral"

                results[sid] = {
                    "score": round(normalized, 4),
                    "raw_score": round(score_val, 4),
                    "signal": signal,
                    "name": strat["name"],
                    "theme": strat["theme"],
                }

            except Exception as e:
                logger.warning("Strategy %s failed: %s", sid, e)
                results[sid] = {"score": 0, "signal": "neutral",
                                "error": str(e)[:80]}

        return results

    def compute_composite(self, df, active_ids=None):
        """Run all strategies and produce a composite signal score.

        Returns:
            dict with:
              - composite_score: float [-1, +1]
              - composite_signal: bullish/bearish/neutral
              - strategy_scores: dict of individual results
              - bullish_count, bearish_count, neutral_count
        """
        scores = self.compute_all(df, active_ids)
        valid = [s["score"] for s in scores.values() if "error" not in s]

        if not valid:
            return {
                "composite_score": 0,
                "composite_signal": "neutral",
                "strategy_scores": scores,
                "bullish_count": 0, "bearish_count": 0, "neutral_count": 0,
            }

        # Weighted average — each strategy contributes equally
        composite = float(np.mean(valid))

        bullish = sum(1 for s in scores.values() if s.get("signal") == "bullish")
        bearish = sum(1 for s in scores.values() if s.get("signal") == "bearish")
        neutral = sum(1 for s in scores.values() if s.get("signal") == "neutral")

        if composite > 0.15:
            signal = "bullish"
        elif composite < -0.15:
            signal = "bearish"
        else:
            signal = "neutral"

        return {
            "composite_score": round(composite, 4),
            "composite_signal": signal,
            "strategy_scores": scores,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
        }


# Singleton
_registry = None

def get_registry():
    """Get the process-wide StrategyRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry


if __name__ == "__main__":
    import yaml
    reg = get_registry()
    print(f"Registered strategies: {len(reg.list())}")
    for s in reg.list():
        print(f"  {s['id']:25} {s['theme']:15} {s['name']}")
