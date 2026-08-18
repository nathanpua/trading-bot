"""Strategies API — multi-factor alpha analysis."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/strategies", tags=["strategies"])
logger = logging.getLogger("dashboard")

# TTL cache for /scan — protects the LSE free-tier quota (200 calls/min)
# from public traffic through the Tailscale Funnel.
_SCAN_CACHE: dict = {}


@router.get("")
def list_strategies():
    """List all registered strategies."""
    try:
        import sys, os
        bot_root = os.environ.get("BOT_ROOT", "/app/bot")
        if bot_root not in sys.path:
            sys.path.insert(0, bot_root)
        from strategy_framework import get_registry
        reg = get_registry()
        strategies = []
        for s in reg.list():
            strategies.append({
                "id": s["id"],
                "name": s["name"],
                "theme": s["theme"],
                "description": s["description"],
                "enabled": s["enabled"],
            })
        return {"strategies": strategies, "count": len(strategies)}
    except Exception as e:
        logger.warning("Strategy list failed: %s", e)
        return {"strategies": [], "count": 0, "error": str(e)[:100]}


@router.get("/scan")
def scan_universe(limit: int = Query(20, ge=1, le=50)):
    """Run all strategies on the trading universe.

    Cached for 5 minutes server-side: each scan costs ~1 LSE API call per
    symbol (25 for the full universe), and the dashboard is publicly exposed
    via Tailscale Funnel — unthrottled public traffic could exhaust the free
    200 calls/min quota the trading bot depends on. The bot itself scans
    through its own path (cron → strategy_engine), unaffected by this cache.
    """
    import time as _time
    cache_key = f"scan_{limit}"
    now = _time.time()
    cached = _SCAN_CACHE.get(cache_key)
    if cached and now - cached[0] < 300:  # 5-minute TTL
        return cached[1]
    try:
        import sys, os
        bot_root = os.environ.get("BOT_ROOT", "/app/bot")
        if bot_root not in sys.path:
            sys.path.insert(0, bot_root)
        from strategy_engine import scan_universe as do_scan
        result = do_scan(max_symbols=limit)
        # Strip non-serializable parts
        payload = {
            "timestamp": result["timestamp"],
            "symbols_scanned": result["symbols_scanned"],
            "symbols_valid": result["symbols_valid"],
            "strategy_count": result["strategy_count"],
            "summary": result["summary"],
            "results": [
                {
                    "symbol": r["symbol"],
                    "composite_score": r.get("composite_score", 0),
                    "composite_signal": r.get("composite_signal", "neutral"),
                    "bullish_count": r.get("bullish_count", 0),
                    "bearish_count": r.get("bearish_count", 0),
                    "neutral_count": r.get("neutral_count", 0),
                    "price": r.get("price", 0),
                    "strategy_scores": {
                        k: {"score": v["score"], "signal": v["signal"],
                            "name": v.get("name", k), "theme": v.get("theme", "")}
                        for k, v in r.get("strategy_scores", {}).items()
                        if "error" not in v
                    },
                }
                for r in result["results"]
            ],
        }
    except Exception as e:
        logger.warning("Strategy scan failed: %s", e)
        return {"error": str(e)[:200], "results": []}

    _SCAN_CACHE[cache_key] = (now, payload)
    return payload

@router.get("/scan/{symbol}")
def scan_symbol(symbol: str):
    """Run all strategies on a single symbol."""
    try:
        import sys, os
        bot_root = os.environ.get("BOT_ROOT", "/app/bot")
        if bot_root not in sys.path:
            sys.path.insert(0, bot_root)
        from strategy_engine import scan_symbol as do_scan
        result = do_scan(symbol.upper())
        return {
            "symbol": result.get("symbol", symbol.upper()),
            "composite_score": result.get("composite_score", 0),
            "composite_signal": result.get("composite_signal", "neutral"),
            "bullish_count": result.get("bullish_count", 0),
            "bearish_count": result.get("bearish_count", 0),
            "neutral_count": result.get("neutral_count", 0),
            "price": result.get("price", 0),
            "strategy_scores": {
                k: {"score": v["score"], "signal": v["signal"],
                    "name": v.get("name", k), "theme": v.get("theme", "")}
                for k, v in result.get("strategy_scores", {}).items()
                if "error" not in v
            },
        }
    except Exception as e:
        return {"symbol": symbol.upper(), "error": str(e)[:200]}
