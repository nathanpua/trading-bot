"""Memory service — wraps trade_memory.py for Supermemory recall."""
from __future__ import annotations

import logging

logger = logging.getLogger("dashboard")

_tm = None


def _get_memory():
    global _tm
    if _tm is None:
        try:
            import sys
            import os
            # Add bot root to path so trade_memory is importable
            from ..config import BOT_ROOT
            bot_root = str(BOT_ROOT)
            if bot_root not in sys.path:
                sys.path.insert(0, bot_root)
            from trade_memory import TradeMemory
            _tm = TradeMemory()
        except Exception as e:
            logger.warning("Supermemory init failed: %s", e)
            _tm = False  # sentinel for "unavailable"
    return _tm if _tm is not False else None


def recall(query: str, limit: int = 5):
    tm = _get_memory()
    if not tm or not tm.connected:
        return []
    return tm.recall(query, limit=limit)


def status():
    tm = _get_memory()
    if not tm:
        return {"connected": False}
    return {"connected": tm.connected}
