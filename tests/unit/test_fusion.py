"""Hand-computed RRF and weighted fusion unit tests."""

from __future__ import annotations

from app.retrieval.fusion import rrf_fuse, weighted_fuse
from app.retrieval.types import ScoredChunk


def _c(cid: str, score: float, doc: str = "d1") -> ScoredChunk:
    return ScoredChunk(
        chunk_id=cid,
        doc_id=doc,
        version=1,
        text=cid,
        score=score,
    )


def test_rrf_hand_computed_k60() -> None:
    """A rank1 dense + rank2 sparse; B rank2 dense + rank1 sparse."""
    dense = [_c("a", 0.9), _c("b", 0.8)]
    sparse = [_c("b", 0.7), _c("a", 0.6)]
    fused = rrf_fuse([dense, sparse], k=60)
    # a: 1/(60+1) + 1/(60+2) = 1/61 + 1/62
    # b: 1/(60+2) + 1/(60+1) = 1/62 + 1/61  → equal scores; tie by chunk_id
    score_a = 1 / 61 + 1 / 62
    score_b = 1 / 62 + 1 / 61
    assert abs(score_a - score_b) < 1e-15
    by_id = {c.chunk_id: c.score for c in fused}
    assert abs(by_id["a"] - score_a) < 1e-12
    assert abs(by_id["b"] - score_b) < 1e-12
    # equal scores → ascending chunk_id: a before b
    assert [c.chunk_id for c in fused] == ["a", "b"]


def test_rrf_single_list_rank() -> None:
    ranked = [_c("x", 1.0), _c("y", 0.5)]
    fused = rrf_fuse([ranked], k=60)
    assert abs(fused[0].score - 1 / 61) < 1e-12
    assert abs(fused[1].score - 1 / 62) < 1e-12
    assert fused[0].chunk_id == "x"


def test_weighted_minmax_hand_computed() -> None:
    """Dense scores 10,0 → norm 1,0; sparse 0,5 → norm 0,1; alpha=0.5."""
    dense = [_c("a", 10.0), _c("b", 0.0)]
    sparse = [_c("a", 0.0), _c("b", 5.0)]
    fused = weighted_fuse(dense, sparse, alpha=0.5)
    by_id = {c.chunk_id: c.score for c in fused}
    # a: 0.5*1 + 0.5*0 = 0.5
    # b: 0.5*0 + 0.5*1 = 0.5
    assert abs(by_id["a"] - 0.5) < 1e-12
    assert abs(by_id["b"] - 0.5) < 1e-12
    assert [c.chunk_id for c in fused] == ["a", "b"]


def test_weighted_alpha_prefers_dense() -> None:
    dense = [_c("a", 1.0), _c("b", 0.0)]
    sparse = [_c("a", 0.0), _c("b", 1.0)]
    fused = weighted_fuse(dense, sparse, alpha=0.8)
    assert fused[0].chunk_id == "a"
    assert abs(fused[0].score - 0.8) < 1e-12
    assert abs(fused[1].score - 0.2) < 1e-12
