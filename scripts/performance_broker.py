#!/usr/bin/env python3
"""
Broker-truth performance report — from the per-cycle BROKER equity series.

Why this exists: the journal's trade-level P&L can drift from reality through
corporate actions (reverse splits), phantom fills, and mark-priced
reconciliations. Live case (Oct 2026): the journal claimed +$17.8k realized
P&L at a 67% win rate while broker equity was up only +2.1% — the difference
was an ETHA reverse-split/short-resolution cascade the journal never modeled.
This script audits performance the way an external auditor would: from the
equity the broker actually reported.

Usage:
    python scripts/performance_broker.py            # monospace table
    python scripts/performance_broker.py --json     # raw JSON
"""
import os, sys, json, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trade_journal as tj


def main():
    ap = argparse.ArgumentParser(description="Broker-truth performance report")
    ap.add_argument("--json", action="store_true", help="output raw JSON")
    args = ap.parse_args()

    perf = tj.get_broker_performance()
    stats = tj.get_stats()

    if args.json:
        print(json.dumps({"broker_performance": perf, "journal_stats": stats}, indent=2))
        return

    if perf.get("status") != "ok":
        print(f"[insufficient equity history: {perf}]")
        return

    o = stats.get("overall", {})
    print("┌─ PERFORMANCE — BROKER TRUTH vs JOURNAL " + "─" * 10)
    print(f"│ Period          {perf['days']} trading days")
    print(f"│ Equity          ${perf['start_equity']:>10,.0f} -> ${perf['current_equity']:>10,.0f}")
    print(f"│ Total return    {perf['total_return_pct']:>10.2f}%   (${perf['total_pnl']:+,.0f})")
    print(f"│ Max drawdown    {perf['max_drawdown_pct']:>10.2f}%")
    if perf.get("sharpe_annualized") is not None:
        print(f"│ Sharpe (ann.)   {perf['sharpe_annualized']:>10.2f}")
    if perf.get("sortino_annualized") is not None:
        print(f"│ Sortino (ann.)  {perf['sortino_annualized']:>10.2f}")
    print("├─ journal (trade-level, may drift) " + "─" * 16)
    if o:
        print(f"│ Journal P&L     ${o.get('total_pnl', 0):>+10,.2f}   ({o.get('trades', 0)} closed trades, "
              f"{o.get('win_rate', 0)}% win rate)")
    print(f"│ Drift           ${perf['drift_pnl']:>+10,.2f}   (journal minus broker — should stay near $0)")
    print("└" + "─" * 48)
    if abs(perf.get("drift_pnl") or 0) > 500:
        print("\n⚠ Journal and broker disagree materially. Treat the BROKER numbers")
        print("  above as truth; run `python trade_journal.py reconcile` to re-align.")


if __name__ == "__main__":
    main()
