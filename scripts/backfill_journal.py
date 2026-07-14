#!/usr/bin/env python3
"""
Backfill trade_journal.db from historical AI trading floor cycle reports.

Reads all cycle_*.json files from reports/trading_floor/, extracts every
executed trade action, and records it to the SQLite journal so the dashboard
Trades and Analysis tabs populate.
"""
import os, sys, json, glob
from pathlib import Path
from datetime import datetime, timezone

BOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT))

import trade_journal as tj

CYCLES_DIR = BOT / "reports" / "trading_floor"

def main():
    tj.init_db()
    files = sorted(CYCLES_DIR.glob("cycle_*.json"))
    print(f"Scanning {len(files)} cycle files...")

    trades_recorded = 0
    cycles_recorded = 0

    # Track open positions to close them properly
    open_positions = {}  # symbol → {entry, qty, strategy, regime, ts}

    for f in files:
        d = json.load(open(f))
        ts = d.get("ts", "")
        execution = d.get("execution", {})
        results = execution.get("results", [])
        executed = execution.get("executed", False)
        plan = d.get("desk_chief_plan", {})
        ctx = d.get("context_summary", {})

        # Record cycle
        regime = ctx.get("regime", "neutral")
        try:
            tj.record_cycle(
                session="ai_floor_backfill",
                regime=regime,
                equity=ctx.get("equity", 0),
                cash_pct=0,
                deployed_pct=0,
                position_count=ctx.get("positions", 0),
                actions=plan.get("actions", []),
                report=plan.get("summary", ""),
            )
            cycles_recorded += 1
        except Exception as e:
            print(f"  cycle record failed: {e}")

        # Record trades
        for r in results:
            status = r.get("status", "")
            if status not in ("submitted", "executed"):
                continue

            act = r.get("action", "").upper()
            sym = r.get("symbol", "").upper()
            if not sym:
                continue

            thesis = r.get("thesis", plan.get("summary", ""))

            if act == "BUY":
                entry = r.get("entry")
                qty = r.get("qty")
                stop = r.get("stop")
                target = r.get("target")
                try:
                    tj.record_trade(
                        symbol=sym, side="BUY",
                        qty=qty, entry_price=entry,
                        stop_price=stop, target_price=target,
                        position_pct=r.get("pos_pct"),
                        risk_pct=r.get("risk_pct"),
                        thesis=thesis,
                        strategy="ai_multi_agent",
                        regime=regime,
                        status="open",
                    )
                    trades_recorded += 1
                    open_positions[sym] = {
                        "entry": entry, "qty": qty, "ts": ts,
                        "strategy": "ai_multi_agent", "regime": regime,
                    }
                    print(f"  {ts[:19]} BUY  {sym:5} qty={qty} @ ${entry}")
                except Exception as e:
                    print(f"  BUY record failed for {sym}: {e}")

            elif act in ("SELL", "CLOSE"):
                qty = r.get("qty")
                # Try to match with an open position
                pos = open_positions.pop(sym, None)
                entry_price = pos["entry"] if pos else r.get("entry")

                # Fetch exit price from Finnhub quote
                exit_price = None
                try:
                    import finnhub_client as fc
                    q = fc.get_quote(sym)
                    exit_price = float(q.get("c") or 0) or None
                except Exception:
                    pass

                # Calculate P&L if we have entry and exit
                pnl_dollars = None
                pnl_pct = None
                close_qty = qty or (pos.get("qty") if pos else 0)
                if entry_price and exit_price and close_qty:
                    pnl_dollars = (float(exit_price) - float(entry_price)) * float(close_qty)
                    if float(entry_price) > 0:
                        pnl_pct = ((float(exit_price) - float(entry_price)) / float(entry_price)) * 100

                # Determine outcome
                if pnl_dollars is not None:
                    outcome = "win" if pnl_dollars > 0 else "loss" if pnl_dollars < 0 else "breakeven"
                else:
                    outcome = "closed"

                # Close existing trade in DB
                try:
                    tj.close_trade(
                        symbol=sym,
                        exit_price=exit_price,
                        pnl_dollars=pnl_dollars,
                        pnl_pct=pnl_pct,
                        outcome=outcome,
                        thesis=thesis,
                    )
                    trades_recorded += 1
                    pnl_str = f"${pnl_dollars:+.2f}" if pnl_dollars is not None else "?"
                    print(f"  {ts[:19]} {act:5} {sym:5} qty={close_qty} exit=${exit_price or '?'} pnl={pnl_str}")
                except Exception as e:
                    print(f"  {act} record failed for {sym}: {e}")

    print(f"\n=== BACKFILL COMPLETE ===")
    print(f"Cycles recorded: {cycles_recorded}")
    print(f"Trades recorded: {trades_recorded}")

    # Show stats
    stats = tj.get_stats()
    overall = stats.get("overall")
    if overall:
        print(f"\nJournal stats:")
        print(f"  Trades: {overall['trades']} | Win rate: {overall['win_rate']}% | Total P&L: ${overall['total_pnl']:,.2f}")
    else:
        print("\nNo closed trades with P&L data found.")

    for s in stats.get("by_strategy", []):
        print(f"  {s['strategy']:20} {s['trades']} trades | {s['win_rate']}% win | ${s['total_pnl']:,.2f}")


if __name__ == "__main__":
    main()
