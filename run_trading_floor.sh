#!/usr/bin/env bash
# Multi-agent trading floor cycle runner.
# 5 AI analysts (macro, news, technicals, risk, memory) → Desk Chief → risk-governed execution.
#
# Usage:
#   ./run_trading_floor.sh                 # dry run (no orders)
#   ./run_trading_floor.sh --execute       # live submit orders (risk-gated)
#   ./run_trading_floor.sh --briefings-only # show analyst briefings only
set -euo pipefail
cd ~/trading-bot
source .venv/bin/activate

# Load GLM API key from Hermes .env
if [ -z "${GLM_API_KEY:-}" ] && [ -f ~/.hermes/.env ]; then
    export GLM_API_KEY=$(grep '^GLM_API_KEY=' ~/.hermes/.env | head -1 | cut -d= -f2- | tr -d "'\"")
    export GLM_BASE_URL=https://api.z.ai/api/coding/paas/v4
fi

echo "┌─ MULTI-AGENT TRADING FLOOR ─ $(date -u '+%Y-%m-%d %H:%M UTC') ─ $(TZ='America/New_York' date '+%H:%M ET')"
echo "│  5 Analysts → Desk Chief → Risk Governor → Execute"
python trading_floor.py "$@"
EXIT=$?
echo "└─ exit $EXIT"
