"""Rank fusion: Reciprocal Rank Fusion and weighted min-max fusion."""

from __future__ import annotations

from collections.abc import Sequence

from app.retrieval.types import ScoredChunk


def rrf_fuse(
    ranked_lists: Sequence[Sequence[ScoredChunk]],
    *,
    k: int = 60,
) -> list[ScoredChunk]:
    """Reciprocal Rank Fusion: score = sum 1/(k + rank) with 1-based ranks.

    Ties broken by chunk_id ascending. Stable sort key: (-score, chunk_id).
    """
    scores: dict[str, float] = {}
    best: dict[str, ScoredChunk] = {}
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            prev = best.get(chunk.chunk_id)
            if prev is None or chunk.score > prev.score:
                best[chunk.chunk_id] = chunk
    fused: list[ScoredChunk] = []
    for cid, score in scores.items():
        base = best[cid]
        fused.append(
            ScoredChunk(
                chunk_id=base.chunk_id,
                doc_id=base.doc_id,
                version=base.version,
                text=base.text,
                score=score,
                chunk_index=base.chunk_index,
                title=base.title,
                heading_path=base.heading_path,
                near_duplicate_of=base.near_duplicate_of,
                content_hash=base.content_hash,
                payload=dict(base.payload),
            )
        )
    fused.sort(key=lambda c: (-c.score, c.chunk_id))
    return fused


def _min_max_normalize(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [1.0 for _ in values]
    span = hi - lo
    return [(v - lo) / span for v in values]


def weighted_fuse(
    dense: Sequence[ScoredChunk],
    sparse: Sequence[ScoredChunk],
    *,
    alpha: float = 0.5,
) -> list[ScoredChunk]:
    """Min-max normalise each list, then ``alpha * dense + (1 - alpha) * sparse``.

    Missing list membership contributes 0 after normalisation. Ties by chunk_id.
    """
    dense_norm = _min_max_normalize([c.score for c in dense])
    sparse_norm = _min_max_normalize([c.score for c in sparse])
    dense_map = {c.chunk_id: (c, n) for c, n in zip(dense, dense_norm, strict=True)}
    sparse_map = {c.chunk_id: (c, n) for c, n in zip(sparse, sparse_norm, strict=True)}
    all_ids = set(dense_map) | set(sparse_map)
    fused: list[ScoredChunk] = []
    for cid in all_ids:
        d_chunk, d_score = dense_map.get(cid, (None, 0.0))
        s_chunk, s_score = sparse_map.get(cid, (None, 0.0))
        base = d_chunk or s_chunk
        assert base is not None
        score = alpha * float(d_score) + (1.0 - alpha) * float(s_score)
        fused.append(
            ScoredChunk(
                chunk_id=base.chunk_id,
                doc_id=base.doc_id,
                version=base.version,
                text=base.text,
                score=score,
                chunk_index=base.chunk_index,
                title=base.title,
                heading_path=base.heading_path,
                near_duplicate_of=base.near_duplicate_of,
                content_hash=base.content_hash,
                payload=dict(base.payload),
            )
        )
    fused.sort(key=lambda c: (-c.score, c.chunk_id))
    return fused
