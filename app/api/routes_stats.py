"""Corpus stats, in-memory metrics, and eval stub."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.documents import DocumentRepository
from app.deps import ChunkStoreDep, DbSession, SettingsDep
from app.index.qdrant_store import collection_name
from app.schemas.query import MetricsResponse, StatsResponse

router = APIRouter(tags=["stats"])


@router.get("/api/stats", response_model=StatsResponse)
def corpus_stats(
    session: DbSession,
    store: ChunkStoreDep,
    settings: SettingsDep,
) -> StatsResponse:
    docs = DocumentRepository(session)
    by_status = docs.counts_by_status(include_deleted=True)
    chunk_total = ChunkRepository(session).count_all()
    coll = getattr(store, "collection", None) or collection_name(
        settings.chunk_strategy,
        settings.embedding_model_short,
    )
    return StatsResponse(
        documents_by_status=by_status,
        document_total=sum(by_status.values()),
        chunk_total=chunk_total,
        collection_name=str(coll),
    )


@router.get("/api/metrics", response_model=MetricsResponse)
def metrics(request: Request, settings: SettingsDep) -> MetricsResponse:
    raw = getattr(request.app.state, "metrics", {}) or {}
    daily = getattr(request.app.state, "llm_daily", None)
    llm_today = daily.count if daily is not None else None
    cap = settings.llm_daily_cap if settings.llm_daily_cap > 0 else None
    return MetricsResponse(
        queries=int(raw.get("queries", 0)),
        uploads=int(raw.get("uploads", 0)),
        errors=int(raw.get("errors", 0)),
        llm_calls_today=llm_today,
        llm_daily_cap=cap,
        extra={k: v for k, v in raw.items() if k not in ("queries", "uploads", "errors")},
    )


@router.get("/api/eval/runs")
def eval_runs() -> dict[str, Any]:
    """Honest stub — evaluation harness is Phase 7."""
    return {
        "runs": [],
        "note": "Evaluation runs are Phase 7; no harness wired yet.",
    }
