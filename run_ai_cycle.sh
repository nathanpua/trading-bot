#!/usr/bin/env bash
# AI-enhanced trading cycle runner — uses GLM 5.2 for decision-making.
# Usage:
#   ./run_ai_cycle.sh           # dry run (no orders)
#   ./run_ai_cycle.sh --execute # live submit orders (risk-gated)
#   ./run_ai_cycle.sh --decide-only  # show AI decision only
set -euo pipefail
cd ~/trading-bot
source .venv/bin/activate

# Load Hermes .env for GLM API key (if not already set)
if [ -z "${GLM_API_KEY:-}" ] && [ -f ~/.hermes/.env ]; then
    export GLM_API_KEY=$(grep '^GLM_API_KEY=' ~/.hermes/.env | head -1 | cut -d= -f2- | tr -d "'\"")
    export GLM_BASE_URL=$(grep '^GLM_BASE_URL=' ~/.hermes/.env | head -1 | cut -d= -f2- | tr -d "'\"" || echo "https://api.z.ai/api/paas/v4")
fi

echo "┌─ AI TRADING CYCLE ─ $(date -u '+%Y-%m-%d %H:%M UTC') ─ $(TZ='America/New_York' date '+%H:%M ET')"
echo "│  Model: GLM 4.7 via Z.AI"
python ai_agent.py "$@"
EXIT=$?
echo "└─ exit $EXIT"
