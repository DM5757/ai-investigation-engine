"""Fixed-size token window chunker with overlap."""

from __future__ import annotations

from app.ingestion.chunking.base import (
    Chunk,
    count_tokens,
    heading_at,
    page_at,
)
from app.ingestion.parsers.base import ParsedDocument


class FixedWindowChunker:
    """Sliding windows of roughly ``chunk_tokens`` with ``overlap_tokens``."""

    name = "fixed_window"

    def chunk(
        self,
        document: ParsedDocument,
        *,
        chunk_tokens: int = 200,
        overlap_tokens: int = 40,
    ) -> list[Chunk]:
        text = document.text
        if not text.strip():
            return []
        if chunk_tokens < 1:
            raise ValueError("chunk_tokens must be >= 1")
        if overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
            raise ValueError("overlap_tokens must be >= 0 and < chunk_tokens")

        tokens = _tokenize_with_spans(text)
        if not tokens:
            return []

        step = max(1, chunk_tokens - overlap_tokens)
        chunks: list[Chunk] = []
        start_idx = 0
        while start_idx < len(tokens):
            end_idx = min(start_idx + chunk_tokens, len(tokens))
            char_start = tokens[start_idx][0]
            char_end = tokens[end_idx - 1][1]
            # Cover leading whitespace on the first window and trailing on the last.
            if start_idx == 0:
                char_start = 0
            if end_idx >= len(tokens):
                char_end = len(text)
            slice_text = text[char_start:char_end]
            if slice_text.strip():
                chunks.append(
                    Chunk(
                        chunk_index=len(chunks),
                        char_start=char_start,
                        char_end=char_end,
                        text=slice_text,
                        heading_path=heading_at(document.spans, char_start),
                        page=page_at(document.spans, char_start),
                        token_count=count_tokens(slice_text),
                        strategy=self.name,
                    )
                )
            if end_idx >= len(tokens):
                break
            start_idx += step

        return chunks


def _tokenize_with_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character spans for whitespace-separated tokens."""
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        while i < n and not text[i].isspace():
            i += 1
        spans.append((start, i))
    return spans
