"""Catalyst scan: earnings dates, company news, economic calendar via Finnhub.
Run: python scripts/catalyst_scan.py
"""
import os, time, requests, pathlib

_BASE = "https://finnhub.io/api/v1"
_env = pathlib.Path("/home/ubuntu/trading-bot/.env")
_key = None
def key():
    global _key
    if _key: return _key
    for line in _env.read_text().splitlines():
        if line.startswith("FINNHUB_API_KEY=") and not line.startswith("#"):
            _key = line.split("=",1)[1].strip().strip("'\"")
            os.environ["FINNHUB_API_KEY"] = _key
            return _key
    raise RuntimeError("no key")

_s = requests.Session()
def g(path, params):
    params = dict(params); params["token"] = key()
    r = _s.get(_BASE + path, params=params, timeout=20)
    r.raise_for_status()
    time.sleep(0.5)
    return r.json()

def pd_ts(t):
    if t is None: return "?"
    try: return time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(t)))
    except Exception: return str(t)

def section(title):
    print("="*60); print(title); print("="*60)

# 1) MU earnings
section("1) MICRON (MU) EARNINGS CALENDAR  Jun 22 - Jul 31, 2026")
try:
    cal = g("/calendar/earnings", {"from":"2026-06-22","to":"2026-07-31"})
    items = cal.get("earningsCalendar", [])
    mu = [x for x in items if (x.get("symbol") or "").upper()=="MU"]
    if mu:
        for x in mu:
            print(f"  MU earnings: {x.get('date')}  estEPS {x.get('epsEstimate')}  rev {x.get('revenueEstimate')}  hour {x.get('hour')}")
    else:
        print(f"  MU not in window Jun22-Jul31. Total entries: {len(items)}. Sample:")
        for x in items[:8]: print(f"    {x.get('symbol')}: {x.get('date')}")
except Exception as e:
    print(f"  ERROR: {e}")

# 2/3) NVDA & AVGO news
for sym in ("NVDA","AVGO"):
    section(f"2/3) COMPANY NEWS  {sym}  last 72h (Jun 19-22, 2026)")
    try:
        news = g("/company-news", {"symbol":sym,"from":"2026-06-19","to":"2026-06-22"})
        print(f"  count={len(news)}")
        for n in news[:8]:
            print(f"  [{pd_ts(n.get('datetime'))}] {n.get('headline','')[:115]}  ({n.get('source','')})")
    except Exception as e:
        print(f"  ERROR: {e}")

# 4) Economic calendar
section("4) US ECONOMIC CALENDAR  Jun 22-27, 2026")
try:
    econ = g("/calendar/economic", {"from":"2026-06-22","to":"2026-06-27"})
    items = econ.get("economicCalendar", econ if isinstance(econ,list) else [])
    us = [x for x in items if (x.get("country") or "").upper()=="US"]
    print(f"  total={len(items)}  US={len(us)}")
    for x in us:
        print(f"  [{x.get('time','?')}] impact={x.get('impact','?')}  {x.get('event','?')[:65]}  actual={x.get('actual')} est={x.get('estimate')}")
except Exception as e:
    print(f"  ERROR: {e}")

# 5) General market news
section("5) MARKET / GENERAL NEWS  last 72h (top headlines)")
try:
    mnews = g("/news", {"category":"general"})
    print(f"  count={len(mnews)}")
    for n in mnews[:14]:
        print(f"  [{pd_ts(n.get('datetime'))}] {n.get('headline','')[:115]}  ({n.get('source','')})")
except Exception as e:
    print(f"  ERROR: {e}")
