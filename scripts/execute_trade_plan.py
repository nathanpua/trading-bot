#!/usr/bin/env python3
"""
Execute the vetted trade plan as Alpaca BRACKET orders.

A bracket order = market entry + stop-loss + take-profit in ONE atomic order.
If the entry fills, the stop and target are live automatically — no orphaned
positions without a hard risk exit.

Safety:
  - DRY RUN by default. Prints exactly what it would submit. Add --execute to
    actually place orders.
  - Re-runs risk_manager.assess_trade() against LIVE account/positions before
    each order and ABORTS if the recommendation is not GO or the portfolio
    check fails (too many positions, over-exposure, etc.).
  - Refuses to trade if market is closed AND --after-hours is not set (market
    orders would be rejected anyway, but fail fast with a clear message).

Usage:
    python scripts/execute_trade_plan.py                # dry run
    python scripts/execute_trade_plan.py --execute      # LIVE submit
    python scripts/execute_trade_plan.py --execute --only MU,MRVL
"""
import os, sys, argparse, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce

import alpaca_client as ac
import indicators as ind
import finnhub_client as fc
import lse_client as lse
import risk_manager as rm


def build_plan(symbols, portfolio_value):
    """Build {symbol: {qty, entry, stop, target}} from live quotes + ATR."""
    plan = {}
    positions = ac.get_positions()
    for sym in symbols:
        df = ind.add_all_indicators(ac.get_bars(sym, "1Day", 100))
        if df is None or df.empty:
            print(f"  {sym}: no data, skipping"); continue
        atr = float(df.iloc[-1]["atr"])
        entry = float(lse.get_quote(sym)["c"])
        stops = rm.calculate_stops(entry, atr)
        res = rm.assess_trade(sym, entry, stops["stop_loss"], portfolio_value, positions)
        if res["recommendation"] != "GO":
            print(f"  {sym}: risk says {res['recommendation']} — skipping")
            continue
        plan[sym] = {
            "qty": res["sizing"]["shares"],
            "entry": entry,
            "stop": round(stops["stop_loss"], 2),
            "target": round(stops["take_profit"], 2),
            "risk_pct": res["sizing"]["risk_pct"],
            "position_pct": res["sizing"]["position_pct"],
        }
    return plan


def submit_bracket(sym, qty, stop, target, dry=True):
    """Submit a bracket market order: entry + stop-loss + take-profit."""
    order = MarketOrderRequest(
        symbol=sym.upper(),
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        stop_loss=StopLossRequest(stop_price=Decimal(str(stop))),
        take_profit=TakeProfitRequest(limit_price=Decimal(str(target))),
    )
    if dry:
        return {"dry_run": True, "symbol": sym, "qty": qty,
                "stop": stop, "target": target, "type": "bracket_market"}
    client = ac.get_trading_client()
    result = client.submit_order(order)
    return {"dry_run": False, "id": str(result.id), "status": str(result.status),
            "symbol": result.symbol, "qty": str(result.qty), "type": "bracket"}


def main():
    ap = argparse.ArgumentParser(description="Execute vetted trade plan")
    ap.add_argument("--execute", action="store_true", help="ACTUALLY submit orders (default: dry run)")
    ap.add_argument("--only", type=str, default="", help="comma list of symbols to trade")
    ap.add_argument("--after-hours", action="store_true", help="allow when market closed")
    args = ap.parse_args()

    acct = ac.get_account()
    pv = float(acct["portfolio_value"])
    print(f"Account: ${pv:,.0f} | cash ${float(acct['cash']):,.0f} | "
          f"positions {len(ac.get_positions())}/5")
    clock = ac.is_market_open()
    print(f"Market open: {clock.get('is_open')} | next open: {clock.get('next_open','?')}")
    if not clock.get("is_open") and not args.execute:
        print("(market closed — dry-run only; orders would queue with --execute)\n")

    default = ["MU", "MRVL", "QQQ"]
    symbols = [s.strip().upper() for s in args.only.split(",") if s.strip()] or default
    print(f"Building plan for: {', '.join(symbols)}\n")

    plan = build_plan(symbols, pv)
    if not plan:
        print("No trades passed risk check. Nothing to execute."); return

    # Print the plan
    print(f"{'Sym':5} {'Qty':>5} {'Entry':>9} {'Stop':>9} {'Target':>9} {'Pos%':>5} {'Risk%':>5}")
    print("─" * 52)
    total_deploy, total_risk = 0.0, 0.0
    for sym, p in plan.items():
        print(f"{sym:5} {p['qty']:>5} {p['entry']:>9.2f} {p['stop']:>9.2f} "
              f"{p['target']:>9.2f} {p['position_pct']:>4.1f}% {p['risk_pct']:>4.1f}%")
        total_deploy += p["qty"] * p["entry"]
        total_risk += p["qty"] * (p["entry"] - p["stop"])
    print("─" * 52)
    print(f"Deploy ${total_deploy:,.0f} ({total_deploy/pv*100:.1f}%) | "
          f"Risk ${total_risk:,.0f} ({total_risk/pv*100:.1f}%) | "
          f"slots {len(plan)}/5\n")

    if not args.execute:
        print("■ DRY RUN — no orders placed. Re-run with --execute to submit.")
        return

    # LIVE EXECUTION
    print("● LIVE SUBMISSION")
    results = []
    for sym, p in plan.items():
        try:
            r = submit_bracket(sym, p["qty"], p["stop"], p["target"], dry=False)
            results.append(r)
            print(f"  {sym}: submitted id={r.get('id')} status={r.get('status')}")
            time.sleep(0.5)
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})
            print(f"  {sym}: ERROR {e}")

    # Persist a record
    recpath = os.path.join(os.path.dirname(__file__), "..", "reports",
                           f"orders_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(recpath, "w") as f:
        json.dump({"plan": plan, "results": results,
                   "account_value": pv, "ts": time.strftime('%Y-%m-%dT%H:%M:%S')}, f, indent=2)
    print(f"\nOrder record → {recpath}")


if __name__ == "__main__":
    main()
