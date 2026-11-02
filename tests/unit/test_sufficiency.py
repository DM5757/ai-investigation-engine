"""Sufficiency gate."""

from __future__ import annotations

from app.investigation.sufficiency import assess_sufficiency
from app.schemas.evidence import Claim, Conflict


def test_insufficient_when_no_claims() -> None:
    status, reason = assess_sufficiency(
        verified_claims=[], conflicts=[], question="Anything?"
    )
    assert status == "insufficient"
    assert reason is not None


def test_missing_metric_attribute_is_insufficient() -> None:
    claims = [
        Claim(
            claim_id="1",
            subject="FraudScorer",
            attribute="statement",
            value="FraudScorer is not listed among root-cause systems.",
            quote="FraudScorer is not listed among root-cause systems.",
            chunk_id="c1",
            doc_id="d1",
            verified=True,
        )
    ]
    status, reason = assess_sufficiency(
        verified_claims=claims,
        conflicts=[],
        question="What was FraudScorer CPU usage during the incident?",
    )
    assert status == "insufficient"
    assert reason is not None


def test_conflicting_status() -> None:
    c = Claim(
        claim_id="1",
        subject="s",
        attribute="a",
        value="v",
        quote="v",
        chunk_id="c",
        doc_id="d",
        verified=True,
    )
    status, _ = assess_sufficiency(
        verified_claims=[c],
        conflicts=[Conflict(subject="s", attribute="a", sides=[c])],
        question="q",
    )
    assert status == "conflicting"
