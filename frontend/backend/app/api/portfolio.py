"""Portfolio API — live account, positions, equity history."""
from __future__ import annotations

from fastapi import APIRouter
from ..services import alpaca_service, journal_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("")
def get_portfolio():
    """Live portfolio snapshot: account + positions + bot state."""
    account = alpaca_service.get_account()
    positions = alpaca_service.get_positions()
    market_open = alpaca_service.is_market_open()
    state = alpaca_service.get_bot_state()
    return {
        "account": account,
        "positions": positions,
        "market_open": market_open,
        "state": state,
    }


@router.get("/equity-history")
def get_equity_history():
    """Equity curve data points from cycle reports."""
    return journal_service.get_equity_history()
