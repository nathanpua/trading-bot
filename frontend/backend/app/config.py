"""Configuration — loads paths and bot .env settings.

Works both in Docker (bot at /app/bot) and locally (bot at parents[N]).
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# Find the bot root: check Docker mount first, then walk up to find it
_here = Path(__file__).resolve()
_candidates = [
    Path("/app/bot"),                             # Docker mount
    _here.parents[2],                             # local: dashboard/backend/app -> dashboard/backend
    _here.parents[3],                             # local: -> dashboard
    _here.parents[4] if len(_here.parents) > 4 else _here.parents[-1],  # -> trading-bot
]

BOT_ROOT = None
for c in _candidates:
    try:
        if (c / "autonomous_engine.py").exists():
            BOT_ROOT = c
            break
    except (OSError, ValueError):
        continue

if not BOT_ROOT:
    # Fallback: try the Docker path
    BOT_ROOT = Path("/app/bot")

# Load the bot's .env for Alpaca/Finnhub keys
_bot_env = BOT_ROOT / ".env"
if _bot_env.exists() and load_dotenv:
    load_dotenv(str(_bot_env))

# Data paths
REPORTS_DIR = BOT_ROOT / "reports"
JOURNAL_DB = REPORTS_DIR / "trade_journal.db"
CYCLE_DIR = REPORTS_DIR / "autonomous"
STATE_FILE = CYCLE_DIR / "state.json"
DATA_DIR = BOT_ROOT / "data"

# API keys (from bot .env)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# App
APP_PORT = int(os.getenv("DASHBOARD_PORT", "8010"))
