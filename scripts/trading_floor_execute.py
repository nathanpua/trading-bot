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
import os, sys, json, argparse, math, logging
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import alpaca_client as ac
import indicators as ind
import risk_manager as rm
import finnhub_client as fc
import lse_client as lse
import breadth
import yaml

logger = logging.getLogger(__name__)

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
    # Last persisted regime snapshot — used to stamp journal buys when the
    # plan doesn't carry a regime (manual/standalone executor runs).
    regime_now = breadth.load_regime_now() or {}
    sleeve_pending = {}  # sleeve name -> BUY cost approved so far this plan

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
            full_qty = float(pos["qty"])

            # Resolve sell quantity: qty_pct takes priority, then qty, then "all".
            # qty_pct is a fraction of the held position (e.g. 0.25 = sell 25%).
            qty_pct = action.get("qty_pct")
            if qty_pct is not None:
                sell_qty = math.floor(full_qty * float(qty_pct))
                if sell_qty < 1:
                    sell_qty = 1  # minimum 1 share for fractional pct on small positions
            else:
                qty = action.get("qty", "all")
                if qty == "all" or qty == "ALL":
                    sell_qty = full_qty
                else:
                    sell_qty = min(float(qty), full_qty)

            exit_price = float(pos["current_price"])
            entry_price = float(pos["avg_entry_price"])
            # Pro-rate P&L for partial sells
            pnl_dollars = float(pos.get("unrealized_pl", 0)) * (sell_qty / full_qty) if full_qty else 0
            pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
            trim_pct_of_pos = round(sell_qty / full_qty * 100, 1) if full_qty else 0
            if dry_run:
                results.append({"action": act, "symbol": sym, "status": "dry_run",
                                "qty": sell_qty, "qty_pct_of_pos": trim_pct_of_pos,
                                "thesis": thesis,
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
                                    "qty": sell_qty, "qty_pct_of_pos": trim_pct_of_pos,
                                    "thesis": thesis,
                                    "entry_price": entry_price,
                                    "exit_price": exit_price,
                                    "pnl_dollars": pnl_dollars,
                                    "pnl_pct": pnl_pct,
                                    "result": r})
                    # Register for FIFO close by reconcile at the REAL fill price
                    try:
                        import trade_journal as tj
                        tj.record_pending(r.get("id"), "sell", {
                            "thesis": f"{act} ({trim_pct_of_pos:.0f}% of position): {thesis[:400]}"})
                    except Exception as e:
                        logger.warning("record_pending(sell %s) failed: %s", sym, e)
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
                quote = lse.get_quote(sym)
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
                max_position_pct=rcfg["max_concentration"],
                size_pct=action.get("size_pct"))
            shares = sizing["shares"]

            if shares <= 0:
                results.append({"action": "BUY", "symbol": sym, "status": "skipped",
                                "reason": "sizing = 0 (risk budget exhausted or stop too tight)"})
                continue

            # Friday half-size: Friday entries were the only negative weekday in
            # the first month of live trading (-$495 over 31 trades). A/B lever.
            notes = []
            fri_factor = float(cfg.get("position_management", {}).get(
                "friday_entry_size_factor", 1.0) or 1.0)
            if 0 < fri_factor < 1.0 and datetime.now(timezone.utc).weekday() == 4:
                shares = int(shares * fri_factor)
                notes.append(f"friday factor {fri_factor} applied")

            # Sleeve cap: correlated universe groups share one exposure budget
            # (e.g. GLD+SLV+GDX combined <= max_sleeve_exposure).
            sleeve = rm.sleeve_of(sym, cfg)
            allowed_value, sleeve_reason = rm.check_sleeve_cap(
                sym, shares * entry, cfg, list(positions.values()), pv,
                pending_value=sleeve_pending.get(sleeve, 0.0))
            if allowed_value <= 0:
                results.append({"action": "BUY", "symbol": sym, "status": "skipped",
                                "reason": sleeve_reason})
                continue
            if allowed_value < shares * entry:
                shares = int(allowed_value / entry)
                if shares < 1:
                    results.append({"action": "BUY", "symbol": sym, "status": "skipped",
                                    "reason": sleeve_reason})
                    continue
                notes.append(sleeve_reason)

            if shares <= 0:
                results.append({"action": "BUY", "symbol": sym, "status": "skipped",
                                "reason": "sizing = 0 after caps"})
                continue

            # Check portfolio limits
            held_count = len(positions) + len([r for r in results if r.get("status") in ("executed", "dry_run") and r.get("action") == "BUY"])
            if (sym not in positions and rcfg.get("max_positions") is not None
                    and held_count >= rcfg["max_positions"]):
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
            if notes:
                order["notes"] = "; ".join(notes)

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
                    sleeve_pending[sleeve] = sleeve_pending.get(sleeve, 0.0) + shares * entry
                    # Register for journal reconciliation with AI context;
                    # reconcile_journal() records it at the REAL fill price.
                    # risk_pct/position_pct are in PERCENT units (0.47 = 0.47%).
                    try:
                        import trade_journal as tj
                        tj.record_pending(str(res.id), "buy", {
                            "thesis": thesis,
                            "strategy": "ai_multi_agent",
                            "regime": action.get("_regime", "") or regime_now.get("regime", ""),
                            "stop_price": round(stop, 2),
                            "target_price": round(target, 2),
                            "position_pct": round(sizing["position_pct"], 1),
                            "risk_pct": round(sizing["risk_pct"], 3),
                        })
                    except Exception as e:
                        logger.warning("record_pending(buy %s) failed: %s", sym, e)
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
