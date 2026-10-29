"""Liveness and readiness endpoints."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.db.session import get_session_factory
from app.db.url import normalize_database_url
from app.deps import SettingsDep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe — no dependency checks."""
    return {"status": "ok"}


@router.get("/api/health/ready")
def ready(request: Request, settings: SettingsDep) -> JSONResponse:
    """Readiness probe — dependency failures return sanitized HTTP 503."""
    db_status = "ok"
    db_detail: str | None = None
    try:
        url = normalize_database_url(settings.database_url)
        factory = get_session_factory(url)
        session = factory()
        try:
            session.execute(text("SELECT 1"))
            session.commit()
        finally:
            session.close()
    except Exception:
        # Never leak driver names, DSNs, or stack traces to clients.
        logger.exception("readiness_database_failed")
        db_status = "unavailable"
        db_detail = "database_unavailable"

    provider = getattr(request.app.state, "embedding_provider", None)
    store = getattr(request.app.state, "chunk_store", None)
    qdrant_status = "configured" if settings.qdrant_url else "local_or_memory"
    if store is not None:
        qdrant_status = "injected"
    llm_status = "degraded"
    if settings.groq_api_key is not None or settings.gemini_api_key is not None:
        llm_status = "configured"

    body: dict[str, Any] = {
        "status": "ready" if db_status == "ok" else "not_ready",
        "database": db_status,
        "embedding_model_configured": settings.embedding_model,
        "embedding_enabled_at_startup": settings.embedding_enabled_at_startup,
        "embedding_loaded": provider is not None,
        "embedding_load_ms": getattr(request.app.state, "embedding_load_ms", None),
        "llm_groq_configured": settings.groq_api_key is not None,
        "llm_gemini_configured": settings.gemini_api_key is not None,
        "llm_status": llm_status,
        "qdrant_configured": settings.qdrant_url is not None,
        "qdrant_status": qdrant_status,
    }
    if db_detail is not None:
        body["error"] = {"code": db_detail, "message": "A required dependency is unavailable"}

    status_code = 200 if db_status == "ok" else 503
    return JSONResponse(status_code=status_code, content=body)


@router.get("/api/version")
def version() -> dict[str, str]:
    return {"version": __version__, "app": "ai-investigation-engine"}


@router.post("/api/bench/embed")
def bench_embed(request: Request, settings: SettingsDep) -> JSONResponse:
    """Phase-1 only: embed one query and return latency.

    Disabled unless ENABLE_BENCH_ENDPOINTS=true.
    """
    if not settings.enable_bench_endpoints:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "bench endpoints disabled"}},
        )
    provider = getattr(request.app.state, "embedding_provider", None)
    if provider is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "embedding_not_loaded",
                    "message": "Set EMBEDDING_ENABLED_AT_STARTUP=true",
                }
            },
        )
    q = request.query_params.get("q", "Which system changes caused payment disruptions?")
    t0 = time.perf_counter()
    vec = provider.embed_query(q)
    latency_ms = (time.perf_counter() - t0) * 1000
    return JSONResponse(
        {
            "ok": True,
            "model": settings.embedding_model,
            "dims": len(vec),
            "latency_ms": round(latency_ms, 3),
            "query_chars": len(q),
        }
    )
