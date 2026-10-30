"""Public investigation / ask endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.ratelimit import DailyCounter, enforce_query_rate_limit
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.documents import DocumentRepository
from app.deps import DbSession, InvestigationEngineDep, SettingsDep
from app.errors import AppError
from app.retrieval.hybrid import RetrievalMode
from app.schemas.evidence import Citation
from app.schemas.query import ALLOWED_MODES, QueryRequest, QueryResponse, SourceEnrichment

router = APIRouter(tags=["query"])


def _excerpt(text: str, limit: int = 400) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _enrich_sources(
    session: Any,
    citations: list[Citation],
    store_payloads: dict[str, dict[str, Any]],
) -> list[SourceEnrichment]:
    chunks = ChunkRepository(session)
    docs = DocumentRepository(session)
    out: list[SourceEnrichment] = []
    for cite in citations:
        payload = store_payloads.get(cite.chunk_id, {})
        row = chunks.get_by_point_id(cite.chunk_id)
        doc = docs.get(cite.doc_id)
        title = None
        version = None
        page = None
        heading: str | None = None
        chunk_text: str | None = None
        if row is not None:
            chunk_text = row.text
            page = row.page
            heading = row.heading_path
            version = row.version
        if payload:
            title = payload.get("title") if isinstance(payload.get("title"), str) else title
            if version is None and payload.get("version") is not None:
                version = int(payload["version"])
            if page is None and payload.get("page") is not None:
                try:
                    page = int(payload["page"])
                except (TypeError, ValueError):
                    page = None
            if heading is None:
                hp = payload.get("heading_path")
                if isinstance(hp, list):
                    heading = " > ".join(str(h) for h in hp)
                elif isinstance(hp, str):
                    heading = hp
            if chunk_text is None and isinstance(payload.get("text"), str):
                chunk_text = payload["text"]
        if title is None and doc is not None:
            title = doc.title
        text = chunk_text or ""
        out.append(
            SourceEnrichment(
                label=cite.label,
                chunk_id=cite.chunk_id,
                doc_id=cite.doc_id,
                quote=cite.quote,
                title=title,
                version=version,
                page=page,
                heading_path=heading,
                chunk_text=chunk_text,
                excerpt=_excerpt(text) if text else None,
            )
        )
    return out


@router.post("/api/query", response_model=QueryResponse)
def query(
    body: QueryRequest,
    request: Request,
    engine: InvestigationEngineDep,
    session: DbSession,
    settings: SettingsDep,
) -> QueryResponse:
    enforce_query_rate_limit(request)
    mode: RetrievalMode = body.mode or "hybrid_rerank"
    if mode not in ALLOWED_MODES:
        raise AppError(f"invalid mode; allowed: {sorted(ALLOWED_MODES)}")

    daily: DailyCounter | None = getattr(request.app.state, "llm_daily", None)
    if (
        daily is not None
        and settings.llm_daily_cap > 0
        and not daily.try_increment(1)
    ):
        from app.api.ratelimit import RateLimited

        raise RateLimited("daily LLM call cap reached")

    # Pin retrieval mode for this investigation (tools use default_mode).
    engine.retriever.default_mode = mode

    metrics = getattr(request.app.state, "metrics", None)
    if isinstance(metrics, dict):
        metrics["queries"] = int(metrics.get("queries", 0)) + 1

    try:
        answer = engine.investigate(body.question.strip())
    except Exception:
        if isinstance(metrics, dict):
            metrics["errors"] = int(metrics.get("errors", 0)) + 1
        raise

    point_ids = [c.chunk_id for c in answer.citations]
    payloads = engine.store.get_payloads(point_ids) if point_ids else {}
    # Also enrich from evidence_preview when citations empty (degraded).
    sources = _enrich_sources(session, answer.citations, payloads)
    if not sources and answer.evidence_preview:
        docs = DocumentRepository(session)
        for i, prev in enumerate(answer.evidence_preview[:8]):
            cid = str(prev.get("chunk_id", ""))
            did = str(prev.get("doc_id", ""))
            text = str(prev.get("text", ""))
            title = prev.get("title") if isinstance(prev.get("title"), str) else None
            if title is None and did:
                doc = docs.get(did)
                if doc is not None:
                    title = doc.title
            sources.append(
                SourceEnrichment(
                    label=f"E{i + 1}",
                    chunk_id=cid,
                    doc_id=did,
                    quote=text[:200],
                    chunk_text=text,
                    excerpt=_excerpt(text),
                    title=title,
                )
            )

    return QueryResponse.from_answer(answer, sources=sources, mode=mode)
