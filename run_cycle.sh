#!/usr/bin/env bash
# Cron runner for the autonomous trading engine.
# Always runs with --execute. The engine self-gates on is_market_open():
# during closed hours it reports only and places no orders. This makes
# --execute safe at any time — the engine is the market-hours authority.
set -euo pipefail
cd ~/trading-bot
source .venv/bin/activate
PHASE="${1:-cycle}"
echo "┌─ AUTONOMOUS TRADE BOT ─ $(date -u '+%Y-%m-%d %H:%M UTC') ─ $(TZ='America/New_York' date '+%H:%M ET')"
python autonomous_engine.py --phase "$PHASE" --execute 2>&1
EXIT=$?
echo "└─ exit $EXIT"
