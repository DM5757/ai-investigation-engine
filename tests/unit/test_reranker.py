"""Unit tests for each reranker feature and post-filters."""

from __future__ import annotations

from app.retrieval.reranker import (
    RerankerWeights,
    apply_per_doc_cap,
    collapse_near_duplicates,
    feature_entity_number_overlap,
    feature_fused_score,
    feature_proximity,
    feature_query_coverage,
    feature_title_heading_match,
    rerank,
)
from app.retrieval.types import ScoredChunk


def _chunk(
    cid: str,
    text: str,
    *,
    score: float = 1.0,
    doc: str = "d1",
    title: str | None = None,
    heading: str | None = None,
    near_dup: str | None = None,
) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=cid,
        doc_id=doc,
        version=1,
        text=text,
        score=score,
        title=title,
        heading_path=heading,
        near_duplicate_of=near_dup,
    )


def test_feature_fused_score_normalised() -> None:
    c = _chunk("a", "x", score=3.0)
    assert feature_fused_score(c, max_score=6.0) == 0.5
    assert feature_fused_score(c, max_score=0.0) == 0.0


def test_feature_query_coverage_hand() -> None:
    # query tokens after stop/stem: payment, failur (of dropped)
    # text has payment only → 1/2
    score = feature_query_coverage("payment failure", "payment processing offline")
    assert abs(score - 0.5) < 1e-9


def test_feature_title_heading_match_hand() -> None:
    score = feature_title_heading_match(
        "payment outage",
        title="Payment Outage Report",
        heading="March Incidents",
    )
    # query: payment, outag — both in title → 1.0
    assert abs(score - 1.0) < 1e-9


def test_feature_entity_number_overlap_hand() -> None:
    score = feature_entity_number_overlap(
        "ServiceX failed on 2024",
        "The ServiceX cluster crashed in 2024 during deploy.",
    )
    # entities/numbers in query: ServiceX, 2024 → both in text
    assert abs(score - 1.0) < 1e-9


def test_feature_proximity_adjacent_vs_far() -> None:
    near = feature_proximity("zymopolymer failure", "zymopolymer failure mode noted")
    far = feature_proximity(
        "zymopolymer failure",
        "zymopolymer " + ("noise " * 40) + "failure",
    )
    assert near > far
    assert near > 0.5


def test_collapse_near_duplicates() -> None:
    items = [
        (_chunk("a", "alpha", doc="d1"), 1.0, {}),
        (_chunk("b", "beta", doc="d2", near_dup="d1"), 0.9, {}),
        (_chunk("c", "gamma", doc="d3"), 0.8, {}),
    ]
    out = collapse_near_duplicates(items)
    assert [t[0].chunk_id for t in out] == ["a", "c"]


def test_per_doc_cap() -> None:
    items = [
        (_chunk("a1", "t", doc="d1"), 1.0, {}),
        (_chunk("a2", "t", doc="d1"), 0.9, {}),
        (_chunk("b1", "t", doc="d2"), 0.8, {}),
    ]
    out = apply_per_doc_cap(items, per_doc_cap=1)
    assert [t[0].chunk_id for t in out] == ["a1", "b1"]


def test_rerank_end_to_end_orders_by_features() -> None:
    chunks = [
        _chunk("weak", "unrelated fluff", score=0.9),
        _chunk(
            "strong",
            "Payment Outage hit ServiceX in 2024",
            score=0.5,
            title="Payment Outage",
        ),
    ]
    hits = rerank(
        "Payment Outage ServiceX 2024",
        chunks,
        weights=RerankerWeights(
            fused=0.1,
            coverage=0.3,
            title_heading=0.3,
            entity_number=0.2,
            proximity=0.1,
        ),
        per_doc_cap=3,
        limit=2,
    )
    assert hits[0].chunk.chunk_id == "strong"
    assert "coverage" in hits[0].feature_scores
