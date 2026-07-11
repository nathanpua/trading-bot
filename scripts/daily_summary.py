#!/usr/bin/env python3
"""
Daily market close summary — runs at 4:00 PM ET via cron (no_agent=True).
Outputs a monospace P&L table delivered to Telegram.

Reads account status, positions, and today's P&L from Alpaca.
Silent on error (empty stdout) so cron doesn't spam failures.
"""

import sys
import os

# Add trading workspace to path
sys.path.insert(0, os.path.expanduser("~/trading-bot"))

try:
    import alpaca_client as a
except ImportError:
    sys.exit(0)  # silent failure

def main():
    try:
        acct = a.get_account()
        positions = a.get_positions()
        clock = a.is_market_open()
    except Exception:
        sys.exit(0)  # silent — don't spam on API errors

    # Header
    lines = []
    lines.append("━━ Daily P&L Summary ━━")
    lines.append("")

    # Account overview
    pv = float(acct["portfolio_value"])
    equity = float(acct["equity"])
    cash = float(acct["cash"])
    day_pl = float(acct["day_pl"])
    day_pl_pct = float(acct["day_plpc"]) * 100

    lines.append(f"Portfolio:  ${pv:,.2f}")
    lines.append(f"Cash:       ${cash:,.2f}")
    lines.append(f"Day Change: ${day_pl:+,.2f} ({day_pl_pct:+.2f}%)")
    lines.append(f"Market:     {'OPEN' if clock['is_open'] else 'CLOSED'}")
    lines.append("")

    # Positions table
    if positions:
        lines.append("Symbol   Shares  AvgCost  CurPrice  P&L$")
        lines.append("──────   ──────  ───────  ────────  ────")
        for p in sorted(positions, key=lambda x: float(x["unrealized_pl"]), reverse=True):
            sym = p["symbol"][:6]
            qty = p["qty"].rstrip("0").rstrip(".") or "0"
            avg = float(p["avg_entry_price"])
            cur = float(p["current_price"])
            pnl = float(p["unrealized_pl"])
            pnl_pct = float(p["unrealized_plpc"]) * 100
            lines.append(f"{sym:<7} {qty:>6}  {avg:>7.2f}  {cur:>8.2f}  {pnl:>+8.2f}")
        lines.append("")
    else:
        lines.append("No open positions.")
        lines.append("")

    # Risk metrics
    num_pos = len(positions)
    exposure = sum(float(p["market_value"]) for p in positions)
    lines.append(f"Positions:  {num_pos}/5")
    lines.append(f"Exposure:   ${exposure:,.0f} ({exposure/pv*100:.1f}%)")
    lines.append(f"Day Trades: {acct['day_trade_count']}")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
