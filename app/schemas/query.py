"""Query API request/response DTOs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.evidence import AnswerResponse, Conflict, UsageStats

RetrievalModeName = Literal[
    "dense",
    "sparse",
    "hybrid_rrf",
    "hybrid_weighted",
    "hybrid_rerank",
]

ALLOWED_MODES: frozenset[str] = frozenset(
    {"dense", "sparse", "hybrid_rrf", "hybrid_weighted", "hybrid_rerank"}
)


class QueryRequest(BaseModel):
    """Public ask payload — only whitelisted retrieval overrides."""

    question: str = Field(..., min_length=1, max_length=4000)
    mode: RetrievalModeName | None = Field(
        default=None,
        description="Optional retrieval mode override (default hybrid_rerank).",
    )


class SourceEnrichment(BaseModel):
    """Citation enriched for the UI sources panel."""

    label: str
    chunk_id: str
    doc_id: str
    quote: str
    title: str | None = None
    version: int | None = None
    page: int | None = None
    heading_path: str | None = None
    chunk_text: str | None = None
    excerpt: str | None = None


class QueryResponse(AnswerResponse):
    """AnswerResponse plus UI-oriented sources and missing_information."""

    sources: list[SourceEnrichment] = Field(default_factory=list)
    missing_information: str | None = None
    mode: str | None = None

    @classmethod
    def from_answer(
        cls,
        answer: AnswerResponse,
        *,
        sources: list[SourceEnrichment],
        mode: str | None = None,
    ) -> QueryResponse:
        missing = answer.abstention_reason
        if answer.status in ("insufficient", "partial", "llm_unavailable") and not missing:
            missing = "Evidence may be incomplete for a full answer."
        data = answer.model_dump()
        return cls(
            **data,
            sources=sources,
            missing_information=missing,
            mode=mode,
        )


class StatsResponse(BaseModel):
    documents_by_status: dict[str, int] = Field(default_factory=dict)
    document_total: int = 0
    chunk_total: int = 0
    collection_name: str | None = None
    origin_note: str = "origin field not tracked; counts are by lifecycle status"


class MetricsResponse(BaseModel):
    queries: int = 0
    uploads: int = 0
    errors: int = 0
    llm_calls_today: int | None = None
    llm_daily_cap: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


# Re-export for OpenAPI clarity
__all__ = [
    "ALLOWED_MODES",
    "Conflict",
    "MetricsResponse",
    "QueryRequest",
    "QueryResponse",
    "RetrievalModeName",
    "SourceEnrichment",
    "StatsResponse",
    "UsageStats",
]
