"""Universe API — view and edit the trading universe in config.yaml."""
from __future__ import annotations

import logging
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/universe", tags=["universe"])
logger = logging.getLogger("dashboard")


def _find_config():
    """Find config.yaml relative to the bot root."""
    candidates = [
        Path("/app/bot/config.yaml"),
        Path(__file__).resolve().parents[4] / "config.yaml",
        Path(__file__).resolve().parents[3] / "config.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _read_universe():
    """Read the universe from config.yaml."""
    import yaml
    cfg_path = _find_config()
    if not cfg_path:
        return {}
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("strategy", {}).get("universe", {})


@router.get("")
def get_universe():
    """Get the current trading universe."""
    universe = _read_universe()
    total = len(set(s for syms in universe.values() for s in syms))
    return {"groups": universe, "total_symbols": total}


@router.get("/symbols")
def get_all_symbols():
    """Get flat list of all symbols in the universe."""
    universe = _read_universe()
    symbols = sorted(set(s for syms in universe.values() for s in syms))
    return {"symbols": symbols, "count": len(symbols)}
