#!/usr/bin/env python3
"""
Strategy Engine — builds market panels and runs multi-strategy analysis.

Usage:
    from strategy_engine import scan_universe
    results = scan_universe()  # scans full config universe
"""

import os, sys, logging, time
from pathlib import Path
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pandas as pd
import yaml

from strategy_framework import get_registry
import alpaca_client as ac
import indicators as ind

logger = logging.getLogger(__name__)
CONFIG_PATH = HERE / "config.yaml"


def _load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_universe_symbols():
    """Get the full trading universe from config."""
    cfg = _load_config()
    universe = cfg.get("strategy", {}).get("universe", {})
    symbols = sorted({s for syms in universe.values() for s in syms})
    return symbols


def scan_symbol(symbol, lookback=120):
    """Run all strategies on a single symbol.

    Returns:
        dict with composite_score, signal, strategy_scores, and price info
    """
    reg = get_registry()

    try:
        df = ind.add_all_indicators(ac.get_bars(symbol, "1Day", lookback))
        if df is None or df.empty or len(df) < 20:
            return {"symbol": symbol, "error": "insufficient data",
                    "composite_score": 0, "composite_signal": "neutral"}

        result = reg.compute_composite(df)
        result["symbol"] = symbol
        result["price"] = float(df.iloc[-1]["close"])
        result["rsi"] = float(df.iloc[-1].get("rsi", 0)) if "rsi" in df.columns else None
        result["adx"] = float(df.iloc[-1].get("adx", 0)) if "adx" in df.columns else None
        return result

    except Exception as e:
        logger.warning("Scan failed for %s: %s", symbol, e)
        return {"symbol": symbol, "error": str(e)[:80],
                "composite_score": 0, "composite_signal": "neutral"}


def scan_universe(symbols=None, max_symbols=50):
    """Scan the full trading universe with all active strategies.

    Returns:
        dict with:
          - timestamp
          - symbols_scanned
          - strategies_active
          - results: list of per-symbol results sorted by composite score
          - summary: aggregate stats
    """
    if symbols is None:
        symbols = get_universe_symbols()

    symbols = symbols[:max_symbols]
    reg = get_registry()
    active = reg.list()

    results = []
    for sym in symbols:
        r = scan_symbol(sym)
        results.append(r)
        time.sleep(0.05)  # light throttle for data API

    # Sort by composite score (bullish first)
    valid = [r for r in results if "error" not in r]
    valid.sort(key=lambda x: x.get("composite_score", 0), reverse=True)

    # Summary
    bullish = [r for r in valid if r.get("composite_signal") == "bullish"]
    bearish = [r for r in valid if r.get("composite_signal") == "bearish"]
    neutral = [r for r in valid if r.get("composite_signal") == "neutral"]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": len(results),
        "symbols_valid": len(valid),
        "strategies_active": [s["id"] for s in active],
        "strategy_count": len(active),
        "results": valid,
        "errors": [r for r in results if "error" in r],
        "summary": {
            "bullish": len(bullish),
            "bearish": len(bearish),
            "neutral": len(neutral),
            "top_bullish": [{"symbol": r["symbol"], "score": r["composite_score"],
                             "strategies": r.get("bullish_count", 0)}
                            for r in bullish[:5]],
            "top_bearish": [{"symbol": r["symbol"], "score": r["composite_score"],
                             "strategies": r.get("bearish_count", 0)}
                            for r in bearish[:5]],
        },
    }


def scan_for_context(held_symbols=None, candidates=None, max_symbols=15):
    """Lightweight scan for AI Desk Chief context.

    Scans held positions + scanner candidates and returns a compact
    strategy assessment for each.
    """
    symbols = list(held_symbols or []) + list(candidates or [])
    symbols = list(dict.fromkeys(symbols))  # dedupe, preserve order
    symbols = symbols[:max_symbols]

    if not symbols:
        return {"status": "no_symbols", "assessments": []}

    reg = get_registry()
    assessments = []

    for sym in symbols:
        r = scan_symbol(sym)
        if "error" in r:
            assessments.append({"symbol": sym, "error": r["error"]})
            continue

        assessments.append({
            "symbol": sym,
            "composite_score": r["composite_score"],
            "composite_signal": r["composite_signal"],
            "bullish_strategies": r.get("bullish_count", 0),
            "bearish_strategies": r.get("bearish_count", 0),
            "total_strategies": r.get("bullish_count", 0) + r.get("bearish_count", 0) + r.get("neutral_count", 0),
            "top_signals": [
                {"strategy": sid, "score": s["score"], "signal": s["signal"]}
                for sid, s in r.get("strategy_scores", {}).items()
                if s.get("signal") != "neutral"
            ][:4],
        })

    return {"status": "ok", "assessments": assessments}


def format_for_llm(scan_result):
    """Format strategy scan results for the AI Desk Chief prompt."""
    lines = ["=== STRATEGY ANALYSIS (Multi-Factor Alpha Zoo) ==="]

    assessments = scan_result.get("assessments", [])
    if not assessments:
        lines.append("(no symbols to analyze)")
        return "\n".join(lines)

    for a in assessments:
        if a.get("error"):
            lines.append(f"  {a['symbol']:5} [ERROR: {a['error'][:50]}]")
            continue

        sym = a["symbol"]
        score = a["composite_score"]
        signal = a["composite_signal"]
        bull = a.get("bullish_strategies", 0)
        bear = a.get("bearish_strategies", 0)
        total = a.get("total_strategies", 0)

        lines.append(
            f"  {sym:5} composite={score:+.2f} ({signal}) "
            f"bullish={bull}/{total} bearish={bear}/{total}"
        )

        for ts in a.get("top_signals", []):
            lines.append(f"        {ts['strategy']:25} {ts['score']:+.2f} {ts['signal']}")

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = scan_universe(max_symbols=10)
    print(f"\nScanned {result['symbols_scanned']} symbols with {result['strategy_count']} strategies")
    print(f"Bullish: {result['summary']['bullish']} | Bearish: {result['summary']['bearish']} | Neutral: {result['summary']['neutral']}")
    print("\nTop symbols:")
    for r in result["results"][:10]:
        print(f"  {r['symbol']:6} score={r['composite_score']:+.3f} signal={r['composite_signal']}")
        for sid, s in r.get("strategy_scores", {}).items():
            if s.get("signal") != "neutral":
                print(f"         {sid:25} {s['score']:+.3f} {s['signal']}")
