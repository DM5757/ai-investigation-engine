"""Thin parse → normalize → chunk orchestration for lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.ingestion.chunking.base import Chunk
from app.ingestion.chunking.registry import get_chunker
from app.ingestion.dedup.hashing import chunk_content_hash, content_hash
from app.ingestion.dedup.simhash import band_values, compute_simhash
from app.ingestion.normalize import normalize_text
from app.ingestion.parsers.base import ParsedDocument, Span
from app.ingestion.parsers.registry import parse_document


@dataclass
class PreparedDocument:
    """Normalized + chunked document ready for persistence / indexing."""

    filename: str
    title: str
    text: str
    content_hash: str
    simhash: int
    bands: list[int]
    chunks: list[Chunk]
    chunk_hashes: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)


ParseFn = Callable[[str, bytes], ParsedDocument]
NormalizeFn = Callable[[str], str]
ChunkFn = Callable[..., list[Chunk]]


def prepare_document(
    filename: str,
    data: bytes,
    *,
    chunk_strategy: str = "structure_aware",
    chunk_tokens: int | None = None,
    overlap_tokens: int | None = None,
    parse_fn: ParseFn | None = None,
    normalize_fn: NormalizeFn | None = None,
    chunk_fn: ChunkFn | None = None,
) -> PreparedDocument:
    """Parse, normalize, hash, SimHash, and chunk a document."""
    settings = get_settings()
    tokens = chunk_tokens if chunk_tokens is not None else settings.chunk_tokens
    overlap = overlap_tokens if overlap_tokens is not None else settings.overlap_tokens

    parser = parse_fn or parse_document
    normalizer = normalize_fn or normalize_text
    parsed = parser(filename, data)
    text = normalizer(parsed.text)
    title = parsed.title or filename
    c_hash = content_hash(text)
    fingerprint = compute_simhash(text)
    bands = band_values(fingerprint)

    normalized_doc = ParsedDocument(
        text=text,
        title=title,
        metadata=dict(parsed.metadata),
        spans=list(parsed.spans),
    )

    if chunk_fn is not None:
        try:
            chunks = chunk_fn(normalized_doc, chunk_tokens=tokens, overlap_tokens=overlap)
        except TypeError:
            chunks = chunk_fn(text, title=title, spans=parsed.spans)
    else:
        chunker = get_chunker(chunk_strategy)
        chunks = chunker.chunk(
            normalized_doc,
            chunk_tokens=tokens,
            overlap_tokens=overlap,
        )

    hashes = [chunk_content_hash(c.text) for c in chunks]
    return PreparedDocument(
        filename=filename,
        title=title,
        text=text,
        content_hash=c_hash,
        simhash=fingerprint,
        bands=bands,
        chunks=chunks,
        chunk_hashes=hashes,
        metadata=dict(parsed.metadata),
        spans=list(parsed.spans),
    )
