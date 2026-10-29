"""Citation verifier strips fabricated labels."""

from __future__ import annotations

from app.investigation.verifier import strip_fabricated_citations, verify_answer_citations
from app.schemas.evidence import Citation, Claim


def test_fabricated_citation_stripped() -> None:
    answer = "Auth-gateway caused issues [S1] and also [S99]."
    citations = [
        Citation(label="S1", chunk_id="c1", doc_id="d1", quote="auth-gateway"),
    ]
    claims = [
        Claim(
            claim_id="1",
            subject="auth",
            attribute="impact",
            value="issues",
            quote="auth-gateway",
            chunk_id="c1",
            doc_id="d1",
            verified=True,
            source_label="S1",
        )
    ]
    cleaned, _, removed, ok = verify_answer_citations(answer, citations, claims)
    assert ok is False
    assert "S99" in removed
    assert cleaned is not None
    assert "[S99]" not in cleaned
    assert "[S1]" in cleaned


def test_strip_helper() -> None:
    text, removed = strip_fabricated_citations("A [S1] B [S2]", {"S1"})
    assert removed == ["S2"]
    assert "[S1]" in text
    assert "[S2]" not in text
