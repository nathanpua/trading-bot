#!/usr/bin/env python3
"""
Trading Floor — State Dumper
Outputs complete portfolio + market state as JSON for analyst agents to read.
Usage: python scripts/trading_floor_state.py [--with-technicals]
"""
import os, sys, json, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import alpaca_client as ac
import indicators as ind
import finnhub_client as fc
import lse_client as lse

def get_state(with_technicals=True):
    acct = ac.get_account()
    positions = ac.get_positions()
    clock = ac.is_market_open()

    state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market_open": clock.get("is_open", False),
        "account": {
            "equity": float(acct["equity"]),
            "cash": float(acct["cash"]),
            "portfolio_value": float(acct["portfolio_value"]),
            "buying_power": float(acct.get("buying_power", 0)),
            "day_trade_count": int(acct.get("daytrade_count", 0)),
            "pattern_day_trader": acct.get("pattern_day_trader", False),
        },
        "positions": [],
        "watchlist_quotes": {},
        "regime_proxies": {},
    }

    # Position details + technicals
    for p in positions:
        sym = p["symbol"]
        pos = {
            "symbol": sym,
            "qty": float(p["qty"]),
            "side": p["side"],
            "entry": float(p["avg_entry_price"]),
            "current": float(p["current_price"]),
            "market_value": float(p["market_value"]),
            "cost_basis": float(p["cost_basis"]),
            "unrealized_pl": float(p["unrealized_pl"]),
            "unrealized_plpc": round(float(p["unrealized_plpc"]) * 100, 2),
            "position_pct": round(float(p["market_value"]) / float(acct["portfolio_value"]) * 100, 2),
        }
        if with_technicals:
            try:
                df = ind.add_all_indicators(ac.get_bars(sym, "1Day", 100))
                df = ind.generate_signals(df)
                last = df.iloc[-1]
                pos["technicals"] = {
                    "rsi": round(float(last.get("rsi", 0)), 1),
                    "macd_diff": round(float(last.get("macd_diff", 0)), 3),
                    "adx": round(float(last.get("adx", 0)), 1),
                    "atr": round(float(last["atr"]), 2),
                    "sma_20": round(float(last["sma_20"]), 2),
                    "sma_50": round(float(last["sma_50"]), 2),
                    "stoch_k": round(float(last.get("stoch_k", 0)), 1),
                    "bb_pos": ("upper" if float(last["close"]) > float(last["bb_high"])
                               else "lower" if float(last["close"]) < float(last["bb_low"]) else "mid"),
                    "buy_score": int(last.get("buy_score", 0)),
                    "sell_score": int(last.get("sell_score", 0)),
                    "trend": "uptrend" if float(last["close"]) > float(last["sma_50"]) else "downtrend",
                }
            except Exception as e:
                pos["technicals"] = {"error": str(e)[:60]}
        state["positions"].append(pos)

    # Regime proxies — use LSE-available symbols
    for sym in ("SPY", "QQQ", "TLT", "GLD", "XLE", "XLF", "EEM"):
        try:
            q = lse.get_quote(sym)
            c = float(q.get("c") or 0)
            if c > 0:
                state["regime_proxies"][sym] = {
                    "price": c, "change_pct": round(float(q.get("dp") or 0), 2)
                }
        except Exception:
            continue

    # Quick quotes for ETF universe
    from strategy_engine import get_universe_symbols
    for sym in get_universe_symbols():
        try:
            q = lse.get_quote(sym)
            c = float(q.get("c") or 0)
            if c > 0:
                state["watchlist_quotes"][sym] = {
                    "price": c, "change_pct": round(float(q.get("dp") or 0), 2)
                }
        except Exception:
            continue

    # Exposure summary
    total_exposure = sum(p["market_value"] for p in state["positions"])
    state["exposure"] = {
        "total": round(total_exposure, 2),
        "pct_of_portfolio": round(total_exposure / float(acct["portfolio_value"]) * 100, 1),
        "position_count": len(state["positions"]),
        "cash_pct": round(float(acct["cash"]) / float(acct["portfolio_value"]) * 100, 1),
    }

    return state

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-technicals", action="store_true", default=True)
    ap.add_argument("--no-technicals", dest="with_technicals", action="store_false")
    args = ap.parse_args()
    print(json.dumps(get_state(args.with_technicals), indent=2))
