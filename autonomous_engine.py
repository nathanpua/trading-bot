#!/usr/bin/env python3
"""
Autonomous Trading Engine — the decision loop.

Cycle: REGIME → KILL-SWITCH → SCAN ENTRIES → MANAGE EXITS → GOVERN → EXECUTE → REPORT

Deterministic by design: every risk check is hard math, never LLM-interpreted.
Designed to run unattended via cron. Fully loggs every decision with rationale.

Usage:
    python autonomous_engine.py                    # full cycle, DRY RUN
    python autonomous_engine.py --execute          # full cycle, LIVE submit
    python autonomous_engine.py --phase report     # P&L snapshot only
"""
import os, sys, json, time, argparse, math, logging
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml
import requests
import alpaca_client as ac
import indicators as ind
import risk_manager as rm
import finnhub_client as fc

logger = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.yaml")
STATE_PATH = os.path.join(HERE, "reports", "autonomous", "state.json")
LOG_PATH = os.path.join(HERE, "reports", "autonomous",
                        f"cycle_{time.strftime('%Y%m%d_%H%M%S')}.json")


# ───────────────────────── config + state ─────────────────────────

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "high_water": None,           # peak equity ($)
        "day_start_equity": None,     # equity at start of trading day ($)
        "day_start_date": None,       # date string for the above
        "halted_until": None,         # ISO timestamp; no new entries until this
        "halt_reason": None,
        "positions": {},              # sym → {entry, entry_date, high, stop, target}
    }


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def update_high_water(state, equity):
    if state["high_water"] is None or equity > state["high_water"]:
        state["high_water"] = equity
    return state


def reset_daily_baseline_if_needed(state, equity):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("day_start_date") != today:
        state["day_start_date"] = today
        state["day_start_equity"] = equity
        # clear a same-day halt when a new day begins
        if state.get("halted_until") and _halt_expired(state):
            state["halted_until"] = None
            state["halt_reason"] = None
    return state


def _halt_expired(state):
    try:
        return datetime.now(timezone.utc) >= datetime.fromisoformat(state["halted_until"])
    except Exception:
        return True


# ───────────────────────── regime ─────────────────────────

def assess_regime(cfg):
    """Read VIX (+ VIXY fallback) + SPY trend → regime + risk multiplier (0.0–1.0)."""
    rcfg = cfg["regime"]
    reasons = []

    # VIX fear gauge — spot VIX not on Finnhub free tier (returns 0); fall
    # back to VIXY (short-term VIX futures ETF) as a fear proxy.
    vix = None; vix_src = None
    for sym in ("VIX", "VIXY", "UVXY"):
        try:
            q = fc.get_quote(sym)
            c = float(q.get("c") or 0)
            if c > 0:
                vix = c; vix_src = sym
                if sym == "UVXY":
                    vix = c / 2  # UVXY is 2x — rough de-lever to compare to spot-ish
                break
        except Exception:
            continue
    if vix is None:
        reasons.append("VIX/VIXY quote unavailable")

    # SPY broad trend
    try:
        spy = ind.add_all_indicators(ac.get_bars("SPY", "1Day", rcfg["spy_trend_lookback"] + 20))
        spy_sma = float(spy.iloc[-1]["sma_50"])
        spy_close = float(spy.iloc[-1]["close"])
        spy_uptrend = spy_close > spy_sma
    except Exception:
        spy_sma = spy_close = None
        spy_uptrend = True  # don't block trading on a data glitch
        reasons.append("SPY trend unavailable (defaulting permissive)")

    # Decide (VIXY trades ~20-30 in calm, spikes >35 in stress; thresholds
    # are calibrated looser than spot VIX since VIXY carries a roll drag).
    proxy_on = rcfg.get("vix_risk_on_threshold", 18)
    proxy_off = rcfg.get("vix_risk_off_threshold", 25)
    mult = 1.0
    if vix is not None:
        if vix >= proxy_off:
            mult *= 0.25; regime = "RISK-OFF"
            reasons.append(f"{vix_src} {vix:.0f} ≥ {proxy_off} (stress)")
        elif vix >= proxy_on:
            mult *= 0.5; regime = "NEUTRAL"
            reasons.append(f"{vix_src} {vix:.0f} elevated (caution)")
        else:
            regime = "RISK-ON"
            reasons.append(f"{vix_src} {vix:.0f} calm")
    else:
        regime = "NEUTRAL"

    if spy_sma is not None:
        if spy_uptrend:
            reasons.append(f"SPY {spy_close:.0f} > SMA50 {spy_sma:.0f} (bullish)")
        else:
            mult *= 0.5
            regime = "NEUTRAL" if regime == "RISK-ON" else regime
            reasons.append(f"SPY {spy_close:.0f} < SMA50 {spy_sma:.0f} (bearish, sizing cut)")

    return {"regime": regime, "risk_multiplier": round(mult, 2),
            "vix": vix, "vix_source": vix_src, "spy_trend": "up" if spy_uptrend else "down",
            "reasons": reasons}


# ───────────────────────── kill switch ─────────────────────────

def check_kill_switch(state, equity, cfg):
    """Return (halt_new_entries: bool, reason: str)."""
    state = update_high_water(state, equity)
    state = reset_daily_baseline_if_needed(state, equity)

    # persistent halt not yet expired
    if state.get("halted_until") and not _halt_expired(state):
        return True, state.get("halt_reason", "halted")

    daily_loss = None
    if state.get("day_start_equity"):
        daily_loss = (equity - state["day_start_equity"]) / state["day_start_equity"]

    drawdown = None
    if state.get("high_water"):
        drawdown = (equity - state["high_water"]) / state["high_water"]

    # daily loss trip
    if daily_loss is not None and daily_loss <= -cfg["risk"]["max_daily_loss"]:
        _set_halt(state, days=0, reason=f"Daily loss {daily_loss*100:.1f}% ≤ -{cfg['risk']['max_daily_loss']*100:.0f}%")
        return True, state["halt_reason"]

    # drawdown trip
    if drawdown is not None and drawdown <= -cfg["risk"]["max_drawdown"]:
        _set_halt(state, days=2, reason=f"Drawdown {drawdown*100:.1f}% ≤ -{cfg['risk']['max_drawdown']*100:.0f}%")
        return True, state["halt_reason"]

    return False, f"OK (daily {'n/a' if daily_loss is None else f'{daily_loss*100:+.1f}%'}, DD {'n/a' if drawdown is None else f'{drawdown*100:+.1f}%'})"


def _set_halt(state, days, reason):
    until = datetime.now(timezone.utc) + timedelta(days=days)
    state["halted_until"] = until.isoformat()
    state["halt_reason"] = reason
    save_state(state)


# ───────────────────────── scanner (entries) ─────────────────────────

def scan_entries(cfg, regime, existing_symbols):
    """Score the universe → ranked candidates passing entry filters.

    Two systematic entry paths (both require uptrend unless overridden):
      1. CONFLUENCE — buy_score ≥ entry_threshold (+ MACD +, oversold/bounce)
      2. MOMENTUM   — strong trend (ADX ≥ 25) + MACD + + RSI in [40,75]
                      (catches trend-continuation names like MU/MRVL that
                      never get oversold enough to score high on confluence)
    """
    scfg = cfg["strategy"]
    universe = sorted({s for syms in scfg["universe"].values() for s in syms})

    candidates = []
    for sym in universe:
        if sym in existing_symbols:
            continue  # already holding
        try:
            df = ind.add_all_indicators(ac.get_bars(sym, "1Day", 120))
            df = ind.generate_signals(df)
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            buy_score = int(last.get("buy_score", 0))
            sell_score = int(last.get("sell_score", 0))
            macd_diff = float(last.get("macd_diff", 0))
            macd_pos = macd_diff > 0
            rsi = float(last.get("rsi", 50))
            adx = float(last.get("adx", 0))
            uptrend = float(last["close"]) > float(last["sma_50"])
            atr = float(last["atr"])

            if sell_score >= 2:
                continue  # bearish confluence — skip
            if scfg["require_uptrend"] and not uptrend:
                continue

            path = None
            # Path 1: confluence (oversold bounce)
            if buy_score >= scfg["entry_threshold"]:
                if scfg["require_macd_positive"] and not macd_pos:
                    pass
                else:
                    path = "confluence"
            # Path 2: momentum (trend continuation)
            if path is None and adx >= 25 and macd_pos and 40 <= rsi <= 75:
                path = "momentum"

            if path is None:
                continue

            candidates.append({
                "symbol": sym, "buy_score": buy_score, "adx": adx,
                "rsi": rsi, "price": float(last["close"]), "atr": atr,
                "path": path,
            })
        except Exception:
            continue

    # rank: confluence wins ties; within, trend strength decides
    candidates.sort(key=lambda c: (c["path"] == "confluence", c["adx"]), reverse=True)
    return candidates


# ───────────────────────── earnings catalyst check ─────────────────────────

_earnings_cache: dict[str, tuple[float, str | None]] = {}
"""symbol → (cache_ts, earnings_date_or_None). TTL = 6h."""

def _check_earnings_within_days(symbol: str, days: int = 5) -> int | None:
    """Return trading days until next earnings, or None if none within `days`.

    Uses Finnhub's earnings calendar. Cached per-symbol for 6h to avoid
    rate-limiting (free tier = 60 req/min).
    """
    now = time.time()
    cached = _earnings_cache.get(symbol)
    if cached and now - cached[0] < 6 * 3600:
        date_str = cached[1]
    else:
        try:
            key = fc._load_key()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            future = (datetime.now(timezone.utc) + timedelta(days=days + 2)).strftime("%Y-%m-%d")
            r = requests.get("https://finnhub.io/api/v1/calendar/earnings", params={
                "symbol": symbol, "from": today, "to": future, "token": key,
            }, timeout=10)
            items = r.json().get("earningsCalendar", [])
            date_str = items[0]["date"] if items else None
            _earnings_cache[symbol] = (now, date_str)
        except Exception as e:
            logger.debug("Earnings check failed for %s: %s", symbol, e)
            _earnings_cache[symbol] = (now, None)
            return None

    if not date_str:
        return None
    try:
        ed = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        diff = (ed - datetime.now(timezone.utc)).days
        return diff if 0 <= diff <= days else None
    except Exception:
        return None


# ───────────────────────── position manager (exits) ─────────────────────────

def manage_positions(cfg, state, execute):
    """Evaluate every open position for trailing stops / signal exits / time stops."""
    mcfg = cfg["position_management"]
    positions = ac.get_positions()
    actions = []

    for p in positions:
        sym = p["symbol"]
        qty = float(p["qty"])
        entry = float(p["avg_entry_price"])
        cur = float(p["current_price"])
        unrealized_pct = (cur - entry) / entry * 100 if entry else 0

        try:
            df = ind.add_all_indicators(ac.get_bars(sym, "1Day", 100))
            df = ind.generate_signals(df)
            last = df.iloc[-1] if df is not None and not df.empty else None
        except Exception:
            df = None
            last = None

        atr = float(last["atr"]) if last is not None else (entry * 0.03)
        macd_diff = float(last.get("macd_diff", 0)) if last is not None else 0
        below_sma = float(last["close"]) < float(last["sma_20"]) if last is not None else False
        risk_per_share = atr * cfg["risk"]["atr_stop_mult"]

        # update tracked high-water for the position
        ps = state["positions"].setdefault(sym, {
            "entry": entry, "entry_date": datetime.now(timezone.utc).isoformat(),
            "high": entry, "stop": entry - risk_per_share,
        })
        ps["high"] = max(ps.get("high", entry), cur)

        # 1) signal-flip exit: thesis invalidated
        #    Two protections to avoid panic-selling at intraday lows:
        #    a) Catalyst grace period — if earnings are within 5 trading days,
        #       suppress the signal-flip and let the ATR stop handle risk.
        #    b) Multi-day confirmation — require MACD neg + below SMA20 on the
        #       last TWO bars, not just one. Prevents one-day noise from
        #       blowing out a position prematurely.
        if mcfg["signal_flip_exit"] and last is not None and macd_diff < 0 and below_sma:
            # Protection a: earnings catalyst grace period
            grace_days = mcfg.get("earnings_grace_days", 5)
            days_to_earnings = _check_earnings_within_days(sym, days=grace_days)
            if days_to_earnings is not None:
                actions.append({"symbol": sym, "action": "HOLD",
                                "reason": f"Signal flip suppressed — earnings in {days_to_earnings}d (catalyst grace period)",
                                "price": cur, "unrealized_pct": unrealized_pct})
                # Still update trailing stop below — don't skip with continue

            # Protection b: require 2 consecutive bearish bars
            elif df is not None and len(df) >= 2:
                prev = df.iloc[-2]
                prev_macd_neg = float(prev.get("macd_diff", 0)) < 0
                prev_below_sma = float(prev["close"]) < float(prev["sma_20"])
                if prev_macd_neg and prev_below_sma:
                    actions.append({"symbol": sym, "action": "CLOSE",
                                    "reason": f"Signal flip confirmed (2 bars): MACD neg ({macd_diff:.2f}) & below SMA20",
                                    "price": cur, "unrealized_pct": unrealized_pct})
                    continue
                else:
                    actions.append({"symbol": sym, "action": "HOLD",
                                    "reason": f"Signal flip unconfirmed — waiting 2nd bar (MACD {macd_diff:.2f} neg but prev bar not both bearish)",
                                    "price": cur, "unrealized_pct": unrealized_pct})
            else:
                actions.append({"symbol": sym, "action": "CLOSE",
                                "reason": f"Signal flip: MACD neg ({macd_diff:.2f}) & below SMA20 (insufficient bars for confirmation)",
                                "price": cur, "unrealized_pct": unrealized_pct})
                continue

        # 2) trailing stop
        profit = cur - ps["entry"]
        activate_r = mcfg["trailing_stop_activate_r"]
        if profit >= activate_r * risk_per_share:
            new_stop = cur - mcfg["trailing_stop_distance_atr"] * atr
            if new_stop > ps.get("stop", 0):
                actions.append({"symbol": sym, "action": "TRAIL_STOP",
                                "reason": f"Trail to {new_stop:.2f} (locked {profit/risk_per_share:.1f}R)",
                                "new_stop": round(new_stop, 2), "qty": qty})
                ps["stop"] = new_stop  # record intent

        # 3) time stop
        days_held = _days_held(ps)
        if days_held >= mcfg["time_stop_days"] and profit < 0:
            actions.append({"symbol": sym, "action": "CLOSE",
                            "reason": f"Time stop: {days_held}d flat/negative ({unrealized_pct:+.1f}%)",
                            "price": cur, "unrealized_pct": unrealized_pct})
            continue

    return actions


def _days_held(ps):
    try:
        ed = datetime.fromisoformat(ps["entry_date"])
        return (datetime.now(timezone.utc) - ed).days
    except Exception:
        return 0


def execute_exit_actions(actions, execute):
    results = []
    for a in actions:
        sym = a["symbol"]
        if a["action"] == "CLOSE":
            if execute:
                try:
                    r = ac.close_position(sym)
                    results.append({**r, **a})
                except Exception as e:
                    results.append({"symbol": sym, "error": str(e), **a})
            else:
                results.append({**a, "dry_run": True})
        elif a["action"] == "TRAIL_STOP":
            if execute:
                try:
                    # cancel existing stop legs, place fresh tighter stop
                    placed = []
                    for o in ac.get_open_orders_for_symbol(sym):
                        ac.cancel_order(o["id"])
                        placed.append(o["id"])
                    r = ac.place_stop_order(sym, a["qty"], a["new_stop"])
                    results.append({**r, "cancelled_legs": placed, **a})
                except Exception as e:
                    results.append({"symbol": sym, "error": str(e), **a})
            else:
                results.append({**a, "dry_run": True})
    return results


# ───────────────────────── entry execution ─────────────────────────

def plan_and_execute_entries(cfg, regime, candidates, execute):
    """Risk-govern each candidate, size by regime, submit bracket orders."""
    rcfg = cfg["risk"]
    acct = ac.get_account()
    pv = float(acct["portfolio_value"])
    cash = float(acct["cash"])
    positions = ac.get_positions()
    held = {p["symbol"] for p in positions}
    exposure = sum(float(p["market_value"]) for p in positions)

    results = []
    for c in candidates:
        if len(positions) + len([r for r in results if r.get("status") == "submitted"]) >= rcfg["max_positions"]:
            results.append({"symbol": c["symbol"], "skip": "max positions reached"})
            continue
        if (exposure / pv) >= rcfg["max_total_exposure"]:
            results.append({"symbol": c["symbol"], "skip": "max total exposure reached"})
            continue

        entry = c["price"]
        stops = rm.calculate_stops(entry, c["atr"], rcfg["atr_stop_mult"], rcfg["reward_ratio"])
        stop, target = stops["stop_loss"], stops["take_profit"]

        # risk-govern with regime multiplier applied to the risk budget
        adj_risk = rcfg["max_risk_per_trade"] * regime["risk_multiplier"]
        sizing = rm.calculate_position_size(pv, entry, stop,
                                            max_risk_pct=adj_risk,
                                            max_position_pct=rcfg["max_concentration"])
        shares = sizing["shares"]
        if shares <= 0:
            results.append({"symbol": c["symbol"], "skip": "sizing=0"})
            continue
        if shares * entry > cash:
            shares = max(0, int(cash / entry))
            if shares <= 0:
                results.append({"symbol": c["symbol"], "skip": "insufficient cash"})
                continue

        order = {"symbol": c["symbol"], "qty": shares, "entry": entry,
                 "stop": round(stop, 2), "target": round(target, 2),
                 "risk_pct": sizing["risk_pct"], "pos_pct": sizing["position_pct"],
                 "thesis": f"{c['path']}: score {c['buy_score']}/5, ADX {c['adx']:.0f}, RSI {c['rsi']:.0f}"}

        if execute:
            try:
                from decimal import Decimal
                from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
                from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
                req = MarketOrderRequest(
                    symbol=c["symbol"], qty=shares, side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY, order_class=OrderClass.BRACKET,
                    stop_loss=StopLossRequest(stop_price=Decimal(str(round(stop, 2)))),
                    take_profit=TakeProfitRequest(limit_price=Decimal(str(round(target, 2)))))
                res = ac.get_trading_client().submit_order(req)
                results.append({**order, "status": "submitted", "id": str(res.id)})
                exposure += shares * entry
                cash -= shares * entry
            except Exception as e:
                results.append({**order, "status": "error", "error": str(e)})
        else:
            results.append({**order, "status": "dry_run"})

    return results


# ───────────────────────── reporting ─────────────────────────

def snapshot_portfolio():
    acct = ac.get_account()
    positions = ac.get_positions()
    lines = []
    lines.append(f"EQUITY   ${float(acct['equity']):>10,.2f}")
    lines.append(f"CASH     ${float(acct['cash']):>10,.2f}")
    lines.append(f"POSITIONS {len(positions)}")
    if positions:
        lines.append("")
        lines.append(f"{'Sym':6}{'Qty':>7}{'Entry':>10}{'Cur':>10}{'P&L$':>10}{'P&L%':>8}")
        lines.append("─" * 51)
        tot = 0.0
        for p in positions:
            pnl = float(p["unrealized_pl"])
            tot += pnl
            pnl_pct = float(p["unrealized_plpc"]) * 100
            lines.append(f"{p['symbol']:6}{float(p['qty']):>7.0f}{float(p['avg_entry_price']):>10.2f}"
                         f"{float(p['current_price']):>10.2f}{pnl:>10.2f}{pnl_pct:>7.1f}%")
        lines.append("─" * 51)
        lines.append(f"{'TOTAL':6}{'':>7}{'':>10}{'':>10}{tot:>10.2f}")
    return "\n".join(lines)


def build_report(phase, regime, kill, entries, exits, execute):
    acct = ac.get_account()
    pv = float(acct["portfolio_value"])
    r = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    r.append(f"{'='*52}")
    r.append(f" AUTONOMOUS CYCLE — {phase.upper()}  [{stamp}]")
    r.append(f" {'LIVE EXECUTION' if execute else 'DRY RUN (no orders)'}")
    r.append(f"{'='*52}\n")
    r.append(f"REGIME: {regime['regime']}  (risk mult {regime['risk_multiplier']})")
    for x in regime["reasons"]:
        r.append(f"  · {x}")
    r.append(f"\nKILL SWITCH: {'HALTED — ' + kill[1] if kill[0] else kill[1]}")
    r.append(f"\nPORTFOLIO (${pv:,.0f}):")
    r.append(snapshot_portfolio())
    if exits:
        r.append(f"\nPOSITION MANAGEMENT ({len(exits)} action(s)):")
        for e in exits:
            tag = "✗" if e.get("action") == "CLOSE" else "↻"
            r.append(f"  {tag} {e['symbol']}: {e['reason']}{' [executed]' if execute and not e.get('dry_run') else ''}")
    else:
        r.append("\nPOSITION MANAGEMENT: none needed (no open positions / no triggers)")
    if entries:
        r.append(f"\nNEW ENTRIES ({len(entries)}):")
        for e in entries:
            if e.get("skip"):
                r.append(f"  ⊘ {e['symbol']}: skipped — {e['skip']}")
            else:
                st = e.get("status", "?")
                r.append(f"  ▸ {e['symbol']} {e.get('qty','?')}sh @ {e.get('entry',0):.2f} "
                         f"stop {e.get('stop',0):.2f} tgt {e.get('target',0):.2f} "
                         f"({e.get('thesis','')}) [{st}]")
    elif not kill[0]:
        r.append("\nNEW ENTRIES: none qualified (no candidate met threshold)")
    elif kill[0]:
        r.append("\nNEW ENTRIES: blocked by kill switch")
    return "\n".join(r)


# ───────────────────────── main loop ─────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Autonomous trading engine")
    ap.add_argument("--execute", action="store_true", help="LIVE submit orders (default: dry run)")
    ap.add_argument("--phase", default="cycle", choices=["cycle", "report"],
                    help="cycle = full decision loop; report = snapshot only")
    args = ap.parse_args()

    cfg = load_config()
    state = load_state()
    acct = ac.get_account()
    equity = float(acct["equity"])
    pv = float(acct["portfolio_value"])

    if args.phase == "report":
        print(f"PORTFOLIO SNAPSHOT (${pv:,.0f})\n{'─'*40}")
        print(snapshot_portfolio())
        print(f"\nstate: {json.dumps({k:v for k,v in state.items() if k!='positions'}, indent=2)}")
        return

    # full cycle
    clock = ac.is_market_open()
    regime = assess_regime(cfg)
    halt, halt_reason = check_kill_switch(state, equity, cfg)
    save_state(state)

    held = {p["symbol"] for p in ac.get_positions()}

    # manage exits regardless of regime/halt (always protect capital)
    exits = manage_positions(cfg, state, args.execute)
    exit_results = execute_exit_actions(exits, args.execute)
    save_state(state)

    # entries only if not halted AND market is open
    entries = []
    if not halt:
        candidates = scan_entries(cfg, regime, held)
        if candidates and clock.get("is_open"):
            entries = plan_and_execute_entries(cfg, regime, candidates, args.execute)
        elif candidates and not clock.get("is_open"):
            entries = [{"symbol": c["symbol"], "skip": "market closed — candidates queued"} for c in candidates]
    else:
        entries = [{"skip": f"halted: {halt_reason}"}]

    report = build_report(args.phase, regime, (halt, halt_reason), entries, exit_results, args.execute)
    print(report)

    # persist machine log
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w") as f:
        json.dump({
            "ts": datetime.now(timezone.utc).isoformat(), "phase": args.phase,
            "execute": args.execute, "regime": regime, "halt": halt,
            "halt_reason": halt_reason, "exits": exit_results, "entries": entries,
            "equity": equity, "report": report,
        }, f, indent=2)
    # also overwrite latest.json for easy cron pickup
    latest = os.path.join(os.path.dirname(LOG_PATH), "latest.json")
    with open(latest, "w") as f:
        json.dump({"report": report, "ts": datetime.now(timezone.utc).isoformat()}, f, indent=2)


if __name__ == "__main__":
    main()
