"""Citation marker parsing / verification coverage."""

from __future__ import annotations

from app.investigation.citations import (
    extract_citation_labels,
    find_malformed_citations,
    strip_citation_markers,
    strip_disallowed_citations,
)
from app.investigation.verifier import verify_answer_citations
from app.schemas.evidence import Citation, Claim
from eval.metrics import exact_match, token_f1


def test_grouped_and_adjacent_citations() -> None:
    assert extract_citation_labels("June 17, 2007 [S1, S2].") == {"S1", "S2"}
    assert extract_citation_labels("ans [S1; S2]") == {"S1", "S2"}
    assert extract_citation_labels("ans [S1][S2]") == {"S1", "S2"}
    assert extract_citation_labels("ans [S1]") == {"S1"}


def test_unicode_and_invisible_citations() -> None:
    # Fullwidth brackets
    assert extract_citation_labels("ans \uff3bS1\uff3d") == {"S1"}
    # Zero-width space inside marker
    assert extract_citation_labels("ans [S1\u200b]") == {"S1"}


def test_malformed_citations_detected() -> None:
    bad = find_malformed_citations("guess [Source1] and [A1]")
    assert any("Source1" in b or "source" in b.lower() for b in bad)
    assert any("A1" in b for b in bad)


def test_strip_for_scoring_removes_markers() -> None:
    assert strip_citation_markers("Woodrum Field [S1].") == "Woodrum Field."
    assert strip_citation_markers("June 17, 2007 [S1, S2].") == "June 17, 2007."
    assert token_f1("Woodrum Field [S1].", "Woodrum Field") == 1.0
    assert exact_match("June 17, 2007 [S1, S2].", "June 17, 2007") == 1.0
    # Legacy pollution: markers become tokens without stripping
    assert token_f1("Woodrum Field [S1].", "Woodrum Field", strip_citations=False) < 1.0


def test_verify_rejects_invented_and_grouped() -> None:
    claims = [
        Claim(
            claim_id="c1",
            subject="a",
            attribute="b",
            value="v",
            quote="q",
            chunk_id="ch1",
            doc_id="d1",
            verified=True,
            source_label="S1",
        )
    ]
    cites = [
        Citation(label="S1", chunk_id="ch1", doc_id="d1", quote="q"),
    ]
    cleaned, _, removed, ok = verify_answer_citations(
        "Answer [S1, S9] and [Source2]",
        cites,
        claims,
    )
    assert not ok
    assert "S9" in removed or any("Source" in r or "source" in r.lower() for r in removed)
    assert "S9" not in (cleaned or "")
    labels = extract_citation_labels(cleaned or "")
    assert "S9" not in labels


def test_strip_disallowed_keeps_valid_group() -> None:
    text, removed = strip_disallowed_citations("ok [S1, S2]", {"S1", "S2"})
    assert removed == []
    assert "[S1, S2]" in text
