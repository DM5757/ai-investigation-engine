"""Citation pruning keeps only answer-supporting labels."""

from __future__ import annotations

from app.investigation.synthesizer import claims_to_citations, prune_citations_to_answer
from app.schemas.evidence import Claim


def test_prune_to_labels_in_answer() -> None:
    claims = [
        Claim(
            claim_id="1",
            subject="Airport",
            attribute="location",
            value="Virginia",
            quote="located in Virginia",
            chunk_id="a:0",
            doc_id="airport",
            verified=True,
            source_label="S1",
        ),
        Claim(
            claim_id="2",
            subject="Other",
            attribute="location",
            value="elsewhere",
            quote="another airport elsewhere",
            chunk_id="b:0",
            doc_id="other",
            verified=True,
            source_label="S2",
        ),
    ]
    citations = claims_to_citations(claims)
    pruned = prune_citations_to_answer(
        "Roanoke–Blacksburg Regional Airport is in Virginia [S1].",
        citations,
    )
    assert len(pruned) == 1
    assert pruned[0].label == "S1"
    assert pruned[0].doc_id == "airport"


def test_prune_empty_answer_returns_no_citations() -> None:
    claims = [
        Claim(
            claim_id="1",
            subject="Airport",
            attribute="location",
            value="Virginia",
            quote="located in Virginia",
            chunk_id="a:0",
            doc_id="airport",
            verified=True,
            source_label="S1",
        )
    ]
    assert prune_citations_to_answer(None, claims_to_citations(claims)) == []
