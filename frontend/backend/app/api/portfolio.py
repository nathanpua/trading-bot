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
    book = journal_service.book_equity()
    account = {**account, "book_equity": book}
    # Day P&L on the BOOK scale. Alpaca's day_pl/day_plpc measure against the
    # whole account (and its last_equity baseline lags corporate actions /
    # liquidations), which showed +$776 on a flat day for the book. The
    # kill-switch day baseline is the authoritative day anchor.
    day_start = state.get("day_start_equity")
    if day_start and float(day_start) > 0 and state.get("day_start_date"):
        book_day_pl = book - float(day_start)
        book_day_pct = book_day_pl / float(day_start)
        account = {**account,
                   "broker_day_pl": account.get("day_pl"),
                   "broker_day_plpc": account.get("day_plpc"),
                   "day_pl": round(book_day_pl, 2),
                   "day_plpc": round(book_day_pct, 6)}
    positions = _attach_stops(positions)
    # Kill-switch state's "positions" map is only maintained by the legacy
    # deterministic engine; the trading floor never fills it — populate from
    # live positions so the panel doesn't claim "Positions tracked: 0" while
    # holding a book.
    if not state.get("positions"):
        state = {**state, "positions": {
            p["symbol"]: {"entry": float(p.get("avg_entry_price") or 0),
                          "stop": p.get("stop_price")}
            for p in positions
        }}
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
    """Equity curve data points from cycle reports (book equity), plus the
    live book point so the home chart reflects now, not the last cycle."""
    history = journal_service.get_equity_history()
    try:
        from datetime import datetime, timezone
        book = journal_service.book_equity()
        now = datetime.now(timezone.utc).isoformat()
        if history and book:
            if str(history[-1].get("ts", ""))[:10] == now[:10]:
                history[-1] = {**history[-1], "ts": now, "equity": book}
            else:
                history.append({"ts": now, "equity": book, "source": "live"})
        elif book:
            history.append({"ts": now, "equity": book, "source": "live"})
    except Exception:
        pass
    return history
