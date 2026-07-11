"""Trades API — historical trade journal."""
from __future__ import annotations

from fastapi import APIRouter, Query
from ..services import journal_service

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("")
def get_trades(
    limit: int = Query(50, ge=1, le=500),
    symbol: str | None = None,
    strategy: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
):
    return journal_service.get_trades(
        limit=limit, symbol=symbol, strategy=strategy,
        status=status, outcome=outcome,
    )


@router.get("/stats")
def get_trade_stats():
    return journal_service.get_stats()
