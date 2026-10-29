"""Shared retrieval result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScoredChunk:
    """A chunk with a retrieval or fusion score."""

    chunk_id: str
    doc_id: str
    version: int
    text: str
    score: float
    chunk_index: int = 0
    title: str | None = None
    heading_path: str | None = None
    near_duplicate_of: str | None = None
    content_hash: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalHit:
    """Final retriever hit with optional explainability fields."""

    chunk: ScoredChunk
    dense_rank: int | None = None
    sparse_rank: int | None = None
    fused_score: float = 0.0
    feature_scores: dict[str, float] = field(default_factory=dict)
    mode: str = ""
