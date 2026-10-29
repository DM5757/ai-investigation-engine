"""Liveness and readiness endpoints."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.deps import DbSession, SettingsDep

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe — no dependency checks."""
    return {"status": "ok"}


@router.get("/api/health/ready")
def ready(request: Request, settings: SettingsDep, session: DbSession) -> dict[str, Any]:
    """Readiness probe — validates configuration and database connectivity."""
    session.execute(text("SELECT 1"))
    provider = getattr(request.app.state, "embedding_provider", None)
    store = getattr(request.app.state, "chunk_store", None)
    qdrant_status = "configured" if settings.qdrant_url else "local_or_memory"
    if store is not None:
        qdrant_status = "injected"
    llm_status = "degraded"
    if settings.groq_api_key is not None or settings.gemini_api_key is not None:
        llm_status = "configured"
    return {
        "status": "ready",
        "database": "ok",
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
