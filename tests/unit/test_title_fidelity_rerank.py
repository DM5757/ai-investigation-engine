"""Reranker prefers exact entity titles over campus extensions."""

from __future__ import annotations

from app.retrieval.reranker import RerankerWeights, feature_title_fidelity, rerank
from app.retrieval.types import ScoredChunk


def _chunk(cid: str, title: str, text: str, score: float = 0.5) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=cid,
        doc_id=cid,
        version=1,
        text=text,
        score=score,
        title=title,
    )


def test_feature_title_fidelity_exact_beats_extension() -> None:
    q = "Is Ohio State University or California State University further west?"
    exact = feature_title_fidelity(q, "Ohio State University")
    campus = feature_title_fidelity(q, "Ohio State University, Mansfield Campus")
    assert exact > campus


def test_rerank_orders_exact_title_above_campus() -> None:
    q = (
        "Is Ohio State University or California State University, "
        "Dominguez Hills further west?"
    )
    chunks = [
        _chunk(
            "mansfield",
            "Ohio State University, Mansfield Campus",
            "Mansfield campus of Ohio State University is in Ohio.",
            score=0.9,
        ),
        _chunk(
            "osu",
            "Ohio State University",
            "The Ohio State University is in Columbus, Ohio.",
            score=0.7,
        ),
        _chunk(
            "csudh",
            "California State University, Dominguez Hills",
            "California State University, Dominguez Hills is in Carson, California.",
            score=0.8,
        ),
    ]
    hits = rerank(
        q,
        chunks,
        weights=RerankerWeights(
            fused=0.2,
            coverage=0.1,
            title_heading=0.1,
            entity_number=0.1,
            proximity=0.05,
            title_fidelity=0.45,
        ),
        per_doc_cap=1,
        limit=3,
    )
    titles = [h.chunk.title for h in hits]
    assert "Ohio State University" in titles
    assert titles.index("Ohio State University") < titles.index(
        "Ohio State University, Mansfield Campus"
    )
