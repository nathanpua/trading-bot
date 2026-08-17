"""
Finnhub news-only client — market news and company news.

Finnhub is retained ONLY for news (the AI trading floor analysts need
headlines and company-specific stories). All market data (OHLCV bars,
real-time quotes) now comes from LSE (lse_client.py).

Public API:
    get_market_news(category, count) -> list[dict]
    get_company_news(symbol, days, count) -> list[dict]
"""

import os
import time
import pathlib
import requests

_BASE = "https://finnhub.io/api/v1"
_HERE = pathlib.Path(__file__).resolve().parent
_ENV_PATH = _HERE / ".env"

_session = requests.Session()
_last_call = 0.0
_MIN_INTERVAL = 0.4  # ~150 req/min ceiling, well under the 60/min free limit when shared


def _load_key():
    """Read FINNHUB_API_KEY from ~/trading-bot/.env (no dotenv dependency)."""
    if os.environ.get("FINNHUB_API_KEY"):
        return os.environ["FINNHUB_API_KEY"]
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("FINNHUB_API_KEY=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    os.environ["FINNHUB_API_KEY"] = val
                    return val
    raise RuntimeError("FINNHUB_API_KEY not set in env or ~/trading-bot/.env")


def _throttle():
    global _last_call
    dt = time.time() - _last_call
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last_call = time.time()


def _get(path, params, timeout=20):
    params = dict(params)
    params["token"] = _load_key()
    _throttle()
    r = _session.get(_BASE + path, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ───────────────────────── news ─────────────────────────
# Finnhub free tier includes /news (market) and /company-news (per-symbol).
# These are the bot's PRIMARY news source — they work reliably via terminal,
# unlike web_search which has no backend configured on this profile.

def get_market_news(category="general", count=50):
    """Latest market news headlines from Finnhub free tier.

    Returns list of dicts: headline, summary, source, url, related, datetime(unix),
    category, id. ``category`` can be 'general', 'forex', 'crypto', 'merger'.
    """
    data = _get("/news", {"category": category})
    if isinstance(data, list):
        return data[:count]
    return []


def get_company_news(symbol, days=7, count=30):
    """Company-specific news for ``symbol`` over the last ``days`` days.

    Returns list of dicts: headline, summary, source, url, related, datetime(unix),
    id, category, image.
    """
    from datetime import datetime, timedelta
    symbol = symbol.upper()
    today = datetime.utcnow()
    frm = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    to = today.strftime("%Y-%m-%d")
    data = _get("/company-news", {"symbol": symbol, "from": frm, "to": to})
    if isinstance(data, list):
        return data[:count]
    return []


if __name__ == "__main__":
    # Smoke test — news only
    import json
    print("== FINNHUB NEWS SMOKE TEST ==\n")
    news = get_market_news(category="general", count=3)
    print(f"Market news: {len(news)} headlines")
    for n in news:
        print(f"  [{n.get('source','')}] {n.get('headline','')[:80]}")
