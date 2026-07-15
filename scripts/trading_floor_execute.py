#!/usr/bin/env python3
"""
Trading Floor — Instruction Executor
Takes a JSON trade plan from the desk chief, risk-gates each action,
and submits bracket orders. The desk chief DECIDES; this script GOVERNS + EXECUTES.

Input (stdin or --file): JSON array of actions:
  [
    {"action": "BUY",  "symbol": "MU",   "thesis": "memory supercycle...", "risk_pct": 0.02},
    {"action": "SELL", "symbol": "NVDA", "thesis": "MACD bearish cross",   "qty": "all"},
    {"action": "CLOSE","symbol": "COIN"},
    {"action": "HOLD"}
  ]

Safety: every BUY passes through risk_manager sizing + concentration cap.
Market-hours gated (BUYs only; CLOSEs execute anytime Alpaca allows).
"""
import os, sys, json, argparse
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import alpaca_client as ac
import indicators as ind
import risk_manager as rm
import finnhub_client as fc
import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    with open(os.path.join(HERE, "config.yaml")) as f:
        return yaml.safe_load(f)


def execute_plan(plan, cfg, dry_run=True):
    """Execute a list of trade actions with full risk governance."""
    rcfg = cfg["risk"]
    acct = ac.get_account()
    pv = float(acct["portfolio_value"])
    cash = float(acct["cash"])
    positions = {p["symbol"]: p for p in ac.get_positions()}
    clock = ac.is_market_open()
    market_open = clock.get("is_open", False)

    results = []
    for action in plan:
        act = action.get("action", "").upper()
        sym = action.get("symbol", "").upper()
        thesis = action.get("thesis", "")

        if act == "HOLD":
            results.append({"action": "HOLD", "thesis": thesis or "no changes needed",
                            "status": "ok"})
            continue

        if act == "CLOSE":
            if sym not in positions:
                results.append({"action": "CLOSE", "symbol": sym, "status": "skipped",
                                "reason": "not held"})
                continue
            pos = positions[sym]
            exit_price = float(pos["current_price"])
            entry_price = float(pos["avg_entry_price"])
            sell_qty = float(pos["qty"])
            pnl_dollars = float(pos.get("unrealized_pl", 0))
            pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100
            if dry_run:
                results.append({"action": "CLOSE", "symbol": sym, "status": "dry_run",
                                "thesis": thesis,
                                "qty": sell_qty,
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "pnl_dollars": pnl_dollars,
                                "pnl_pct": pnl_pct})
            else:
                try:
                    for o in ac.get_open_orders_for_symbol(sym):
                        ac.cancel_order(o["id"])
                    r = ac.close_position(sym)
                    results.append({"action": "CLOSE", "symbol": sym, "status": "executed",
                                    "thesis": thesis, "qty": sell_qty,
                                    "entry_price": entry_price,
                                    "exit_price": exit_price,
                                    "pnl_dollars": pnl_dollars,
                                    "pnl_pct": pnl_pct,
                                    "result": r})
                except Exception as e:
                    results.append({"action": "CLOSE", "symbol": sym, "status": "error",
                                    "error": str(e)[:100]})
            continue

        if act in ("SELL", "TRIM"):
            if sym not in positions:
                results.append({"action": act, "symbol": sym, "status": "skipped",
                                "reason": "not held"})
                continue
            pos = positions[sym]
            qty = action.get("qty", "all")
            if qty == "all" or qty == "ALL":
                sell_qty = float(pos["qty"])
            else:
                sell_qty = min(float(qty), float(pos["qty"]))
            exit_price = float(pos["current_price"])
            entry_price = float(pos["avg_entry_price"])
            # Pro-rate P&L for partial sells
            full_qty = float(pos["qty"])
            pnl_dollars = float(pos.get("unrealized_pl", 0)) * (sell_qty / full_qty) if full_qty else 0
            cost_basis = entry_price * sell_qty
            pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
            if dry_run:
                results.append({"action": act, "symbol": sym, "status": "dry_run",
                                "qty": sell_qty, "thesis": thesis,
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "pnl_dollars": pnl_dollars,
                                "pnl_pct": pnl_pct})
            else:
                try:
                    # Cancel any open orders (bracket legs) holding the shares
                    for o in ac.get_open_orders_for_symbol(sym):
                        ac.cancel_order(o["id"])
                    r = ac.place_market_order(sym, side="sell", qty=sell_qty)
                    results.append({"action": act, "symbol": sym, "status": "executed",
                                    "qty": sell_qty, "thesis": thesis,
                                    "entry_price": entry_price,
                                    "exit_price": exit_price,
                                    "pnl_dollars": pnl_dollars,
                                    "pnl_pct": pnl_pct,
                                    "result": r})
                except Exception as e:
                    results.append({"action": act, "symbol": sym, "status": "error",
                                    "error": str(e)[:100]})
            continue

        if act == "BUY":
            if not market_open:
                results.append({"action": "BUY", "symbol": sym, "status": "skipped",
                                "reason": "market closed — queued for next open"})
                continue

            # Get current data for sizing
            try:
                quote = fc.get_quote(sym)
                entry = float(quote.get("c") or 0)
                if entry <= 0:
                    df = ind.add_all_indicators(ac.get_bars(sym, "1Day", 100))
                    entry = float(df.iloc[-1]["close"])
                df = ind.add_all_indicators(ac.get_bars(sym, "1Day", 100))
                atr = float(df.iloc[-1]["atr"])
            except Exception as e:
                results.append({"action": "BUY", "symbol": sym, "status": "error",
                                "error": f"data: {str(e)[:60]}"})
                continue

            stops = rm.calculate_stops(entry, atr, rcfg["atr_stop_mult"], rcfg["reward_ratio"])
            stop, target = stops["stop_loss"], stops["take_profit"]

            # Regime multiplier (desk chief can pass it, or default to 1.0)
            risk_mult = action.get("risk_multiplier", 1.0)
            risk_pct = min(action.get("risk_pct", rcfg["max_risk_per_trade"]),
                           rcfg["max_risk_per_trade"]) * risk_mult

            sizing = rm.calculate_position_size(
                pv, entry, stop,
                max_risk_pct=risk_pct,
                max_position_pct=rcfg["max_concentration"])
            shares = sizing["shares"]

            if shares <= 0:
                results.append({"action": "BUY", "symbol": sym, "status": "skipped",
                                "reason": "sizing = 0 (risk budget exhausted or stop too tight)"})
                continue

            # Check portfolio limits
            held_count = len(positions) + len([r for r in results if r.get("status") in ("executed", "dry_run") and r.get("action") == "BUY"])
            if sym not in positions and held_count >= rcfg["max_positions"]:
                results.append({"action": "BUY", "symbol": sym, "status": "skipped",
                                "reason": f"max positions ({rcfg['max_positions']}) reached"})
                continue

            if shares * entry > cash:
                shares = max(1, int(cash / entry))
                if shares * entry > cash:
                    results.append({"action": "BUY", "symbol": sym, "status": "skipped",
                                    "reason": "insufficient cash"})
                    continue

            order = {
                "action": "BUY", "symbol": sym, "qty": shares, "entry": round(entry, 2),
                "stop": round(stop, 2), "target": round(target, 2),
                "risk_pct": round(sizing["risk_pct"], 3),
                "pos_pct": round(sizing["position_pct"], 1),
                "cost": round(shares * entry, 2),
                "thesis": thesis,
            }

            if dry_run:
                order["status"] = "dry_run"
                results.append(order)
            else:
                try:
                    from alpaca.trading.requests import (MarketOrderRequest,
                        StopLossRequest, TakeProfitRequest)
                    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
                    req = MarketOrderRequest(
                        symbol=sym, qty=shares, side=OrderSide.BUY,
                        time_in_force=TimeInForce.DAY, order_class=OrderClass.BRACKET,
                        stop_loss=StopLossRequest(stop_price=Decimal(str(round(stop, 2)))),
                        take_profit=TakeProfitRequest(limit_price=Decimal(str(round(target, 2)))))
                    res = ac.get_trading_client().submit_order(req)
                    order["status"] = "submitted"
                    order["order_id"] = str(res.id)
                    results.append(order)
                    cash -= shares * entry
                except Exception as e:
                    order["status"] = "error"
                    order["error"] = str(e)[:100]
                    results.append(order)
            continue

        results.append({"action": act, "symbol": sym, "status": "unknown_action"})

    return results


def main():
    ap = argparse.ArgumentParser(description="Trading floor instruction executor")
    ap.add_argument("--file", help="JSON plan file (default: stdin)")
    ap.add_argument("--execute", action="store_true", help="LIVE submit (default: dry run)")
    ap.add_argument("--plan", help="Inline JSON plan string")
    args = ap.parse_args()

    if args.file:
        with open(args.file) as f:
            plan = json.load(f)
    elif args.plan:
        plan = json.loads(args.plan)
    else:
        plan = json.loads(sys.stdin.read())

    if isinstance(plan, dict):
        plan = [plan]

    cfg = load_config()
    results = execute_plan(plan, cfg, dry_run=not args.execute)

    acct = ac.get_account()
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "executed": args.execute,
        "starting_equity": float(acct["equity"]),
        "actions": results,
        "summary": {
            "total": len(results),
            "executed": len([r for r in results if r.get("status") in ("submitted", "executed")]),
            "dry_run": len([r for r in results if r.get("status") == "dry_run"]),
            "skipped": len([r for r in results if r.get("status") == "skipped"]),
            "errors": len([r for r in results if r.get("status") == "error"]),
        },
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
