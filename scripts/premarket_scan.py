#!/usr/bin/env python3
"""
Pre-market watchlist scan — runs at 9:00 AM ET via cron (no_agent=True).
Outputs a monospace signal table for the default watchlist.

Silent on error (empty stdout) so cron doesn't spam failures.
"""

import sys
import os

sys.path.insert(0, os.path.expanduser("~/trading-bot"))

try:
    import alpaca_client as a
    import indicators as i
except ImportError:
    sys.exit(0)

WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "AMD", "COIN", "PLTR",
    "SPY", "QQQ",
]


def main():
    try:
        clock = a.is_market_open()
    except Exception:
        sys.exit(0)

    try:
        results = i.scan_watchlist(WATCHLIST)
    except Exception:
        sys.exit(0)

    lines = []
    lines.append("━━ Pre-Market Scan ━━")
    
    status = "OPEN" if clock["is_open"] else "PRE-MARKET"
    lines.append(f"Market: {status}")
    lines.append("")

    # Filter to actionable signals
    buy_signals = [r for r in results if r.get("signal") == 1 and "error" not in r]
    sell_signals = [r for r in results if r.get("signal") == -1 and "error" not in r]
    neutral = [r for r in results if r.get("signal") == 0 and "error" not in r]

    if buy_signals:
        lines.append("▲ BUY SIGNALS")
        lines.append("Symbol   Price    RSI   Score")
        lines.append("──────   ──────   ───  ─────")
        for r in sorted(buy_signals, key=lambda x: x.get("buy_score", 0), reverse=True):
            rsi = f"{r['rsi']:.0f}" if r.get("rsi") else "—"
            lines.append(f"{r['symbol']:<7} {r['close']:>7.2f}  {rsi:>3}  {r['buy_score']}/5")
        lines.append("")

    if sell_signals:
        lines.append("▼ SELL SIGNALS")
        lines.append("Symbol   Price    RSI   Score")
        lines.append("──────   ──────   ───  ──────")
        for r in sorted(sell_signals, key=lambda x: x.get("sell_score", 0), reverse=True):
            rsi = f"{r['rsi']:.0f}" if r.get("rsi") else "—"
            lines.append(f"{r['symbol']:<7} {r['close']:>7.2f}  {rsi:>3}  {r['sell_score']}/5")
        lines.append("")

    if not buy_signals and not sell_signals:
        lines.append("No strong signals today.")
        lines.append(f"{len(neutral)} symbols neutral")
        lines.append("")

    # Show neutral summary compactly
    if neutral:
        lines.append("Neutral watch:")
        for r in neutral[:5]:
            rsi = f"RSI {r['rsi']:.0f}" if r.get("rsi") else ""
            lines.append(f"  {r['symbol']:<5} {r['close']:>7.2f}  {rsi}")
        if len(neutral) > 5:
            lines.append(f"  +{len(neutral)-5} more")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
