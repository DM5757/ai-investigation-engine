"""Structure-aware chunker: pack sentences under heading context."""

from __future__ import annotations

from app.ingestion.chunking.base import (
    Chunk,
    count_tokens,
    heading_at,
    page_at,
)
from app.ingestion.chunking.sentences import Sentence, split_sentences
from app.ingestion.parsers.base import ParsedDocument, Span

# Allow a small packing overshoot when a single sentence exceeds the budget.
_SIZE_TOLERANCE = 32


class StructureAwareChunker:
    """Pack sentences into chunks, preferring heading boundaries.

    Stored chunk ``text`` is the clean document slice (no header prefix).
    Optional ``context_header`` records the heading path used for embedding.
    """

    name = "structure_aware"

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

        sentences = split_sentences(text)
        if not sentences:
            return []

        packs = _pack_sentences(
            sentences,
            document.spans,
            chunk_tokens=chunk_tokens,
            overlap_tokens=overlap_tokens,
        )
        chunks: list[Chunk] = []
        for pack in packs:
            char_start = pack[0].start
            char_end = pack[-1].end
            # Extend to include interstitial whitespace up to next content.
            slice_text = text[char_start:char_end]
            if not slice_text.strip():
                continue
            heading = heading_at(document.spans, char_start)
            chunks.append(
                Chunk(
                    chunk_index=len(chunks),
                    char_start=char_start,
                    char_end=char_end,
                    text=slice_text,
                    heading_path=heading,
                    page=page_at(document.spans, char_start),
                    token_count=count_tokens(slice_text),
                    strategy=self.name,
                    context_header=heading,
                )
            )
        return _ensure_full_coverage(chunks, text)



def _pack_sentences(
    sentences: list[Sentence],
    spans: list[Span],
    *,
    chunk_tokens: int,
    overlap_tokens: int,
) -> list[list[Sentence]]:
    packs: list[list[Sentence]] = []
    current: list[Sentence] = []
    current_tokens = 0
    current_heading = heading_at(spans, sentences[0].start)

    def flush() -> list[Sentence]:
        nonlocal current, current_tokens
        if not current:
            return []
        packs.append(current)
        overlap = _overlap_tail(current, overlap_tokens)
        current = list(overlap)
        current_tokens = sum(count_tokens(s.text) for s in current)
        return overlap

    for sent in sentences:
        sent_heading = heading_at(spans, sent.start)
        sent_tokens = max(1, count_tokens(sent.text))

        heading_changed = sent_heading != current_heading and current
        would_exceed = current and (current_tokens + sent_tokens > chunk_tokens)

        if heading_changed or would_exceed:
            flush()
            current_heading = sent_heading
            # After flush, current may hold overlap from previous pack.
            if current and heading_changed:
                current = []
                current_tokens = 0

        if not current and sent_tokens > chunk_tokens + _SIZE_TOLERANCE:
            # Oversized single sentence: emit alone.
            packs.append([sent])
            current = []
            current_tokens = 0
            current_heading = sent_heading
            continue

        current.append(sent)
        current_tokens += sent_tokens
        current_heading = sent_heading

    if current:
        packs.append(current)
    return packs


def _overlap_tail(sentences: list[Sentence], overlap_tokens: int) -> list[Sentence]:
    if overlap_tokens <= 0 or not sentences:
        return []
    tail: list[Sentence] = []
    tokens = 0
    for sent in reversed(sentences):
        t = count_tokens(sent.text)
        if tail and tokens + t > overlap_tokens:
            break
        tail.append(sent)
        tokens += t
        if tokens >= overlap_tokens:
            break
    tail.reverse()
    return tail


def _ensure_full_coverage(chunks: list[Chunk], text: str) -> list[Chunk]:
    """Stretch bounds so the union of ranges covers ``[0, len(text)]``."""
    if not chunks or not text:
        return chunks
    fixed: list[Chunk] = []
    for idx, chunk in enumerate(chunks):
        start = 0 if idx == 0 else chunk.char_start
        if idx + 1 < len(chunks):
            next_start = chunks[idx + 1].char_start
            end = next_start if chunk.char_end < next_start else chunk.char_end
        else:
            end = len(text)
        new_text = text[start:end]
        fixed.append(
            Chunk(
                chunk_index=idx,
                char_start=start,
                char_end=end,
                text=new_text,
                heading_path=chunk.heading_path,
                page=chunk.page,
                token_count=count_tokens(new_text),
                strategy=chunk.strategy,
                context_header=chunk.context_header,
            )
        )
    return fixed
