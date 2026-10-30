"""Question-conditioned sufficiency gate (+ conflict short-circuit)."""

from __future__ import annotations

from app.investigation.entities import claim_covers_entity, extract_focus_entities
from app.investigation.question_focus import (
    QuestionFocus,
    claim_support_score,
    extract_question_focus,
    filter_claims_for_question,
)
from app.schemas.evidence import AnswerStatus, Claim, Conflict


def assess_sufficiency(
    *,
    verified_claims: list[Claim],
    conflicts: list[Conflict],
    question: str,
    focus: QuestionFocus | None = None,
    min_support: float = 0.55,
) -> tuple[AnswerStatus, str | None]:
    """Return (status, abstention_reason) using question-conditioned evidence.

    Distinguishes contradictory evidence, missing evidence, generic keyword-only
    overlap (insufficient), thin/partial subject coverage, and answerable support.
    """
    if conflicts:
        return "conflicting", "Independent sources disagree on the same attribute."

    if not verified_claims:
        return (
            "insufficient",
            "No verified claims could be grounded in retrieved document quotes.",
        )

    q_focus = focus or extract_question_focus(question)
    supporting, weak, _ = filter_claims_for_question(
        verified_claims, question, min_support=min_support
    )

    if not supporting:
        if weak:
            return (
                "insufficient",
                "Retrieved passages only share generic keywords with the question "
                "and do not support the asked subject or relationship.",
            )
        return (
            "insufficient",
            "No verified claims could be grounded in retrieved document quotes.",
        )

    entities = extract_focus_entities(question)
    if len(entities) >= 2:
        covered: list[str] = []
        for ent in entities:
            for claim in supporting:
                hay = (
                    f"{claim.source_title or ''} {claim.subject} {claim.attribute} "
                    f"{claim.value} {claim.quote}"
                )
                if claim_covers_entity(hay, ent):
                    covered.append(ent)
                    break
        if len(covered) < 2:
            return (
                "insufficient",
                "Comparison or multi-hop question requires grounded evidence for "
                "each named entity; retrieved claims cover fewer than two entities.",
            )

    scores = [claim_support_score(c, q_focus) for c in supporting]
    best = max(scores) if scores else 0.0
    multi = [p for p in q_focus.phrases if len(p.replace("-", " ").split()) >= 2]
    if multi and best < 0.75 and len(entities) < 2:
        return (
            "partial",
            "Evidence partially overlaps the question but does not clearly "
            "cover the primary named subject or requested fact.",
        )

    return "answered", None
