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


def test_temporal_deploy_time_conflict_across_docs() -> None:
    claims = [
        Claim(
            claim_id="a",
            subject="Change Log",
            attribute="statement",
            value="Deployed auth-gateway 2.4.1 at 14:00 UTC on 2024-03-12.",
            quote="Deployed auth-gateway 2.4.1 at 14:00 UTC on 2024-03-12.",
            chunk_id="c1",
            doc_id="changelog",
            verified=True,
        ),
        Claim(
            claim_id="b",
            subject="Postmortem",
            attribute="statement",
            value="Timeline starts at 08:10 UTC with AuthGateway deploy.",
            quote="Timeline starts at 08:10 UTC with AuthGateway deploy.",
            chunk_id="c2",
            doc_id="postmortem",
            verified=True,
        ),
    ]
    # Temporal pairing is question-gated to avoid false conflicts on
    # unrelated "who / what" questions that merely share deploy docs.
    conflicts = candidate_conflicts(
        claims,
        question="At what time was auth-gateway deployed? Note contradictions.",
    )
    assert len(conflicts) >= 1
    values = " ".join(s.value for c in conflicts for s in c.sides)
    assert "14:00" in values
    assert "08:10" in values


def test_causal_root_cause_conflict_across_docs() -> None:
    jwt_quote = (
        "A misconfigured JWT TTL on AuthGateway caused cascading "
        "retries into PaymentService."
    )
    neon_quote = (
        "Release notes claim the outage was caused by a Neon connection "
        "pool exhaustion, not JWT TTL."
    )
    claims = [
        Claim(
            claim_id="a",
            subject="Incident",
            attribute="statement",
            value="JWT TTL caused cascading retries.",
            quote=jwt_quote,
            chunk_id="c1",
            doc_id="incident",
            verified=True,
        ),
        Claim(
            claim_id="b",
            subject="Change Log",
            attribute="statement",
            value="Neon connection pool exhaustion, not JWT TTL.",
            quote=neon_quote,
            chunk_id="c2",
            doc_id="changelog",
            verified=True,
        ),
    ]
    conflicts = candidate_conflicts(
        claims,
        question=(
            "What do the documents say about root cause of payment outage? "
            "Note contradictions."
        ),
    )
    assert len(conflicts) >= 1
    assert any(c.attribute == "root_cause" for c in conflicts)


def test_no_causal_conflict_without_cause_question() -> None:
    jwt_quote = (
        "A misconfigured JWT TTL on AuthGateway caused cascading "
        "retries into PaymentService."
    )
    neon_quote = (
        "Release notes claim the outage was caused by a Neon connection "
        "pool exhaustion, not JWT TTL."
    )
    claims = [
        Claim(
            claim_id="a",
            subject="Incident",
            attribute="statement",
            value="JWT TTL caused cascading retries.",
            quote=jwt_quote,
            chunk_id="c1",
            doc_id="incident",
            verified=True,
        ),
        Claim(
            claim_id="b",
            subject="Change Log",
            attribute="statement",
            value="Neon connection pool exhaustion, not JWT TTL.",
            quote=neon_quote,
            chunk_id="c2",
            doc_id="changelog",
            verified=True,
        ),
    ]
    assert (
        candidate_conflicts(claims, question="Who approved the auth-gateway rollback?")
        == []
    )


def test_no_temporal_conflict_without_time_question() -> None:
    claims = [
        Claim(
            claim_id="a",
            subject="Change Log",
            attribute="statement",
            value="Deployed auth-gateway 2.4.1 at 14:00 UTC on 2024-03-12.",
            quote="Deployed auth-gateway 2.4.1 at 14:00 UTC on 2024-03-12.",
            chunk_id="c1",
            doc_id="changelog",
            verified=True,
        ),
        Claim(
            claim_id="b",
            subject="Postmortem",
            attribute="statement",
            value="Timeline starts at 08:10 UTC with AuthGateway deploy.",
            quote="Timeline starts at 08:10 UTC with AuthGateway deploy.",
            chunk_id="c2",
            doc_id="postmortem",
            verified=True,
        ),
    ]
    assert candidate_conflicts(claims, question="Who approved the rollback?") == []
