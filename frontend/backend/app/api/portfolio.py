"""Portfolio API — live account, positions, equity history."""
from __future__ import annotations

from fastapi import APIRouter
from ..services import alpaca_service, journal_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("")
def get_portfolio():
    """Live portfolio snapshot: account + positions + bot state."""
    account = alpaca_service.get_account()
    positions = alpaca_service.get_positions()
    market_open = alpaca_service.is_market_open()
    state = alpaca_service.get_bot_state()
    # book_equity = base_capital + realized + unrealized — the number the bot
    # actually trades and risks against (account equity includes idle cash)
    account = {**account, "book_equity": journal_service.book_equity()}
    positions = _attach_stops(positions)
    return {
        "account": account,
        "positions": positions,
        "market_open": market_open,
        "state": state,
    }


def _attach_stops(positions):
    """Attach each position's stop/target levels.

    Source of truth order: journal open lots (stamped by the executor /
    reconciliation), then the broker's live bracket stop legs (held state).
    The autonomous-engine state map only fills in when that engine runs —
    the trading floor path doesn't maintain it, so without this the
    Positions tab shows no stops at all.
    """
    stops = {}
    try:
        conn = journal_service._get_db()
        if conn:
            for r in conn.execute("""
                    SELECT symbol, MIN(stop_price) AS stop, MAX(target_price) AS tgt
                    FROM trades WHERE status='open' AND stop_price IS NOT NULL
                    GROUP BY symbol"""):
                stops[r["symbol"].upper()] = (float(r["stop"]), float(r["tgt"]) if r["tgt"] else None)
            conn.close()
    except Exception:
        pass
    if not stops:
        try:
            import alpaca_client as _ac
            for o in _ac.get_orders(status="open", limit=100):
                sym = str(o.get("symbol", "")).upper()
                if "STOP" in str(o.get("type", "")).upper():
                    stops.setdefault(sym, (float(o.get("stop_price") or 0) or None, None))
        except Exception:
            pass
    out = []
    for p in positions:
        sym = str(p.get("symbol", "")).upper()
        stop, tgt = stops.get(sym, (None, None))
        out.append({**p, "stop_price": stop, "target_price": tgt})
    return out


@router.get("/equity-history")
def get_equity_history():
    """Equity curve data points from cycle reports."""
    return journal_service.get_equity_history()
