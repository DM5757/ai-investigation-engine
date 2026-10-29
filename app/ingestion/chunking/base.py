"""Chunk types and chunker protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.ingestion.parsers.base import ParsedDocument, Span


@dataclass(slots=True)
class Chunk:
    """A contiguous slice of document text prepared for indexing."""

    chunk_index: int
    char_start: int
    char_end: int
    text: str
    heading_path: str | None
    page: int | None
    token_count: int
    strategy: str
    context_header: str | None = None


class Chunker(Protocol):
    """Strategy that turns a ParsedDocument into ordered Chunks."""

    name: str

    def chunk(
        self,
        document: ParsedDocument,
        *,
        chunk_tokens: int = 200,
        overlap_tokens: int = 40,
    ) -> list[Chunk]:
        """Split document into chunks."""
        ...


def count_tokens(text: str) -> int:
    """Deterministic whitespace token estimate (no external tokenizer)."""
    if not text or not text.strip():
        return 0
    return len(text.split())


def span_at(spans: list[Span], offset: int) -> Span | None:
    """Return the span covering ``offset``, if any."""
    for span in spans:
        if span.start <= offset < span.end:
            return span
    return None


def heading_at(spans: list[Span], offset: int) -> str | None:
    span = span_at(spans, offset)
    return span.heading_path if span else None


def page_at(spans: list[Span], offset: int) -> int | None:
    span = span_at(spans, offset)
    return span.page if span else None
