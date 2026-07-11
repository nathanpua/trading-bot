#!/usr/bin/env python3
"""
News scanner for the trading floor news analyst.

Pulls market-wide headlines + per-symbol company news from Finnhub's free-tier
news endpoints. This is the bot's PRIMARY news source — it works reliably via
terminal, unlike web_search which has no backend configured on this profile.

Usage:
    python scripts/news_scan.py                     # market news only
    python scripts/news_scan.py MU NVDA AMD         # market + company news for symbols
    python scripts/news_scan.py --holdings          # auto-pull current Alpaca holdings
    python scripts/news_scan.py MU --company-only   # skip market headlines
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import finnhub_client as fc


def fmt_ts(unix_ts):
    """Unix timestamp → 'Jun 25 09:30' string."""
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).strftime("%b %d %H:%M")
    except Exception:
        return "??"


def print_market_news(count=25):
    """Print top market headlines."""
    try:
        news = fc.get_market_news(category="general", count=count)
    except Exception as e:
        print(f"  [market news error: {e}]")
        return

    print(f"{'='*70}")
    print(f" MARKET NEWS — {len(news)} headlines")
    print(f"{'='*70}")
    for a in news:
        src = a.get("source", "?")
        ts = fmt_ts(a.get("datetime"))
        head = a.get("headline", "")
        related = a.get("related", "").strip()
        tag = f"  [{related}]" if related else ""
        print(f"  [{ts} | {src:8s}] {head}{tag}")
        summary = a.get("summary", "")
        if summary:
            print(f"    → {summary[:140]}")
    print()


def print_company_news(symbol, days=7, count=15):
    """Print company-specific news for a symbol."""
    try:
        news = fc.get_company_news(symbol, days=days, count=count)
    except Exception as e:
        print(f"  [{symbol} news error: {e}]")
        return

    print(f"{'─'*70}")
    print(f" {symbol} COMPANY NEWS — {len(news)} articles (last {days}d)")
    print(f"{'─'*70}")
    if not news:
        print("  (no recent news)")
        print()
        return
    for a in news:
        src = a.get("source", "?")
        ts = fmt_ts(a.get("datetime"))
        head = a.get("headline", "")
        print(f"  [{ts} | {src:8s}] {head}")
        summary = a.get("summary", "")
        if summary:
            print(f"    → {summary[:140]}")
    print()


def get_holdings():
    """Return list of symbols currently held in the Alpaca account."""
    try:
        import alpaca_client as ac
        return [p["symbol"] for p in ac.get_positions()]
    except Exception:
        return []


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    company_only = "--company-only" in sys.argv
    use_holdings = "--holdings" in sys.argv

    symbols = list(args)
    if use_holdings:
        symbols = get_holdings()
        if not symbols:
            print("No open positions to scan.")
            return

    # Market news (unless --company-only)
    if not company_only:
        print_market_news(count=25)

    # Company news for each requested symbol
    for sym in symbols:
        print_company_news(sym.upper(), days=7, count=15)

    # Summary footer
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[news_scan complete — {stamp}]")


if __name__ == "__main__":
    main()
