"""Analysis API — stats, memory recall, lessons."""
from __future__ import annotations

from fastapi import APIRouter, Query
from ..services import journal_service, memory_service

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/stats")
def get_stats():
    return journal_service.get_stats()


@router.get("/memory")
def recall_memory(q: str = Query(..., min_length=2), limit: int = Query(5, ge=1, le=20)):
    results = memory_service.recall(q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@router.get("/memory/status")
def memory_status():
    return memory_service.status()
