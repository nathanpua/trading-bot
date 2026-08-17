"""Catalyst scan: company news + economic calendar.
  - News: Finnhub (market + company news)
  - Economic calendar: LSE (replaces Finnhub economic calendar)
  - Earnings: N/A (ETF universe has no earnings)

Run: python scripts/catalyst_scan.py
"""
import os, sys, time, pathlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import finnhub_client as fc
import lse_client as lse

def pd_ts(t):
    if t is None: return "?"
    try: return time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(t)))
    except Exception: return str(t)

def section(title):
    print("="*60); print(title); print("="*60)

# 1) Company news for top ETFs
for sym in ("SPY", "QQQ", "GLD"):
    section(f"1) COMPANY NEWS  {sym}  last 7 days")
    try:
        news = fc.get_company_news(sym, days=7, count=8)
        print(f"  count={len(news)}")
        for n in news[:8]:
            print(f"  [{pd_ts(n.get('datetime'))}] {n.get('headline','')[:115]}  ({n.get('source','')})")
    except Exception as e:
        print(f"  ERROR: {e}")

# 2) Economic calendar via LSE
section("2) US ECONOMIC CALENDAR  (next 7 days)")
try:
    from datetime import datetime, timedelta
    start = datetime.utcnow().strftime("%Y-%m-%d")
    end = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")
    events = lse.get_economic_calendar(region="US", start=start, end=end)
    print(f"  total events: {len(events)}")
    for e in events[:15]:
        print(f"  [{e.get('date','?')}] impact={e.get('importance','?')}  {e.get('event','?')[:65]}  actual={e.get('actual')} est={e.get('forecast')}")
except Exception as e:
    print(f"  ERROR: {e}")

# 3) General market news
section("3) MARKET / GENERAL NEWS  (top headlines)")
try:
    mnews = fc.get_market_news(category="general", count=14)
    print(f"  count={len(mnews)}")
    for n in mnews[:14]:
        print(f"  [{pd_ts(n.get('datetime'))}] {n.get('headline','')[:115]}  ({n.get('source','')})")
except Exception as e:
    print(f"  ERROR: {e}")
