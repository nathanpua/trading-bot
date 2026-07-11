"""Cycles API — bot cycle reports and regime history."""
from __future__ import annotations

from fastapi import APIRouter, Query
from ..services import journal_service

router = APIRouter(prefix="/api/cycles", tags=["cycles"])


@router.get("")
def get_cycles(limit: int = Query(20, ge=1, le=100)):
    return journal_service.get_cycles(limit=limit)
