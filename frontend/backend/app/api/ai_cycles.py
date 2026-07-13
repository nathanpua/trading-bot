"""AI Cycles API — multi-agent trading floor cycle reports."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Query

from ..config import REPORTS_DIR

router = APIRouter(prefix="/api/ai-cycles", tags=["ai-cycles"])
logger = logging.getLogger("dashboard")

# AI cycle logs live in reports/trading_floor/ (multi-agent) and reports/ai_cycles/ (single-agent)
TF_DIR = REPORTS_DIR / "trading_floor"
AI_DIR = REPORTS_DIR / "ai_cycles"


def _load_cycle(filepath: Path) -> dict | None:
    """Load a single cycle JSON, returning a summary dict."""
    try:
        data = json.loads(filepath.read_text())
        plan = data.get("desk_chief_plan") or data.get("plan") or {}
        actions = plan.get("actions", [])
        briefings = data.get("briefings", {})
        execution = data.get("execution", {})
        ctx = data.get("context_summary", {})

        return {
            "ts": data.get("ts", ""),
            "model": data.get("model", ""),
            "elapsed_seconds": data.get("elapsed_seconds"),
            "mode": "trading_floor" if "briefings" in data else "single_agent",
            "equity": ctx.get("equity", 0),
            "position_count": ctx.get("positions", 0),
            "candidate_count": ctx.get("candidates", 0),
            "regime": ctx.get("regime", ""),
            "actions": actions,
            "summary": plan.get("summary", ""),
            "confidence": plan.get("confidence", ""),
            "analysis": plan.get("analysis", {}),
            "briefings": briefings,
            "execution": execution,
            "report": data.get("report", ""),
            "raw_response": data.get("raw_response", ""),
        }
    except Exception as e:
        logger.warning("Failed to load AI cycle %s: %s", filepath.name, e)
        return None


@router.get("")
def get_ai_cycles(limit: int = Query(20, ge=1, le=100)):
    """List recent AI trading floor cycles (newest first)."""
    cycles = []

    # Multi-agent trading floor cycles
    if TF_DIR.exists():
        for f in sorted(TF_DIR.glob("cycle_*.json"), reverse=True)[:limit]:
            c = _load_cycle(f)
            if c:
                cycles.append(c)

    # Single-agent AI cycles (if fewer multi-agent cycles exist)
    multi_count = len(cycles)
    if multi_count < limit and AI_DIR.exists():
        for f in sorted(AI_DIR.glob("cycle_*.json"), reverse=True)[:limit - multi_count]:
            c = _load_cycle(f)
            if c:
                cycles.append(c)

    # Sort all by timestamp descending
    cycles.sort(key=lambda c: c.get("ts", ""), reverse=True)
    return cycles[:limit]


@router.get("/latest")
def get_latest_ai_cycle():
    """Get the most recent AI cycle with full detail."""
    for d in (TF_DIR, AI_DIR):
        if not d.exists():
            continue
        files = sorted(d.glob("cycle_*.json"), reverse=True)
        # Also check latest.json
        latest = d / "latest.json"
        if latest.exists():
            return _load_cycle(latest) or {}
        if files:
            return _load_cycle(files[0]) or {}
    return {}
