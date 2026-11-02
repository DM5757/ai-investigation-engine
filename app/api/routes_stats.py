"""Corpus stats, in-memory metrics, and published evaluation summary."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.documents import DocumentRepository
from app.deps import ChunkStoreDep, DbSession, SettingsDep
from app.index.qdrant_store import collection_name
from app.schemas.query import MetricsResponse, StatsResponse

router = APIRouter(tags=["stats"])

_PUBLISHED_EVAL = Path(__file__).resolve().parents[1] / "data" / "published_eval.json"


@lru_cache(maxsize=1)
def _load_published_eval() -> dict[str, Any]:
    if not _PUBLISHED_EVAL.is_file():
        return {
            "runs": [],
            "note": "Published evaluation artifact missing from image.",
            "limitations": [],
        }
    raw: Any = json.loads(_PUBLISHED_EVAL.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {
            "runs": [],
            "note": "Published evaluation artifact is invalid JSON object.",
            "limitations": [],
        }
    return raw


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
    """Serve measured evaluation summary baked into the image (not live re-scoring)."""
    data = dict(_load_published_eval())
    data.setdefault(
        "note",
        "Held-out metrics from committed artifacts. Smoke demos are not overall accuracy.",
    )
    return data
