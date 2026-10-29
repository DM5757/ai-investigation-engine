"""Deterministic sufficiency gate (+ optional LLM polish)."""

from __future__ import annotations

from app.schemas.evidence import AnswerStatus, Claim, Conflict


def assess_sufficiency(
    *,
    verified_claims: list[Claim],
    conflicts: list[Conflict],
    question: str,
) -> tuple[AnswerStatus, str | None]:
    """Return (status, abstention_reason)."""
    _ = question
    if conflicts:
        return "conflicting", "Independent sources disagree on the same attribute."
    if not verified_claims:
        return (
            "insufficient",
            "No verified claims could be grounded in retrieved document quotes.",
        )
    docs = {c.doc_id for c in verified_claims}
    if len(verified_claims) == 1 and len(docs) == 1:
        # Single shard of evidence — answerable but thin
        return "answered", None
    return "answered", None
