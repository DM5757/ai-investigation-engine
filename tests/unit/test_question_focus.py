"""Question focus extraction and claim support scoring."""

from __future__ import annotations

from app.investigation.question_focus import (
    claim_support_score,
    extract_question_focus,
    filter_claims_for_question,
)
from app.investigation.sufficiency import assess_sufficiency
from app.schemas.evidence import Claim


def _claim(quote: str, *, subject: str = "x", doc_id: str = "d1") -> Claim:
    return Claim(
        claim_id=f"{doc_id}-1",
        subject=subject,
        attribute="statement",
        value=quote[:80],
        quote=quote,
        chunk_id=f"{doc_id}:0",
        doc_id=doc_id,
        verified=True,
    )


def test_extracts_multi_token_phrase() -> None:
    focus = extract_question_focus(
        "What happened to the Roanoke Colony disappearance?"
    )
    assert any("roanoke" in p.lower() and "colony" in p.lower() for p in focus.phrases)


def test_airport_claim_does_not_support_colony_question() -> None:
    question = "What happened to the Roanoke Colony and why did it disappear?"
    airport = _claim(
        "Roanoke–Blacksburg Regional Airport is a public airport in Virginia.",
        subject="Roanoke–Blacksburg Regional Airport",
        doc_id="airport",
    )
    supporting, weak, _ = filter_claims_for_question([airport], question)
    assert supporting == []
    assert weak
    status, reason = assess_sufficiency(
        verified_claims=[airport], conflicts=[], question=question
    )
    assert status == "insufficient"
    assert reason is not None


def test_airport_claim_supports_airport_question() -> None:
    question = (
        "What is Roanoke–Blacksburg Regional Airport, and where is it located?"
    )
    airport = _claim(
        "Roanoke–Blacksburg Regional Airport, also known as Woodrum Field, "
        "is approximately 6 km northwest of downtown Roanoke, Virginia.",
        subject="Roanoke–Blacksburg Regional Airport",
        doc_id="airport",
    )
    score = claim_support_score(airport, extract_question_focus(question))
    assert score >= 0.55
    status, _ = assess_sufficiency(
        verified_claims=[airport], conflicts=[], question=question
    )
    assert status in ("answered", "partial")


def test_generic_keyword_only_is_insufficient() -> None:
    question = "What caused the Zymopolymer reactor meltdown?"
    unrelated = _claim(
        "PaymentService latency spiked after the March deploy.",
        subject="PaymentService",
        doc_id="pay",
    )
    status, _ = assess_sufficiency(
        verified_claims=[unrelated], conflicts=[], question=question
    )
    assert status == "insufficient"
