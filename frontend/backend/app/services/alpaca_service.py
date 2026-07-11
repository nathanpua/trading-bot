"""Alpaca service — wraps bot's alpaca_client.py with caching."""
from __future__ import annotations

import time
import logging
from typing import Any

logger = logging.getLogger("dashboard")

_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 45  # seconds


def _cached(key: str, fn, ttl=CACHE_TTL):
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    try:
        result = fn()
        _cache[key] = (now, result)
        return result
    except Exception as e:
        logger.warning("Alpaca call failed (%s): %s", key, e)
        # Return stale cache if available
        if key in _cache:
            return _cache[key][1]
        raise


def get_account() -> dict:
    import alpaca_client as ac
    return _cached("account", ac.get_account)


def get_positions() -> list[dict]:
    import alpaca_client as ac
    raw = _cached("positions", ac.get_positions, ttl=30)
    if isinstance(raw, list):
        return raw
    return [raw] if raw else []


def get_orders(limit: int = 50) -> list[dict]:
    import alpaca_client as ac
    return _cached(f"orders_{limit}", lambda: ac.get_orders(limit=limit), ttl=60)


def is_market_open() -> bool:
    import alpaca_client as ac
    return _cached("market_open", ac.is_market_open, ttl=30)


def get_bot_state() -> dict:
    import json
    from ..config import STATE_FILE
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}
