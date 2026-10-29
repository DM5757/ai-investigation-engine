"""Contradiction candidate generation."""

from __future__ import annotations

from app.investigation.contradictions import candidate_conflicts
from app.schemas.evidence import Claim


def _claim(cid: str, doc: str, value: str) -> Claim:
    return Claim(
        claim_id=cid,
        subject="PaymentService",
        attribute="march_status",
        value=value,
        quote=value,
        chunk_id=cid,
        doc_id=doc,
        verified=True,
    )


def test_contradiction_candidate_pairs() -> None:
    claims = [
        _claim("a", "docA", "disrupted after auth-gateway deploy"),
        _claim("b", "docB", "zero incidents in March"),
    ]
    conflicts = candidate_conflicts(claims)
    assert len(conflicts) == 1
    assert len(conflicts[0].sides) >= 2


def test_no_conflict_when_values_agree() -> None:
    claims = [
        _claim("a", "docA", "disrupted"),
        _claim("b", "docB", "disrupted"),
    ]
    assert candidate_conflicts(claims) == []
