"""Question-conditioned sufficiency gate (+ conflict short-circuit)."""

from __future__ import annotations

import re

from app.investigation.entities import (
    claim_covers_entity,
    entity_title_fidelity,
    extract_focus_entities,
    is_comparison_question,
)
from app.investigation.question_focus import (
    QuestionFocus,
    claim_support_score,
    extract_question_focus,
    filter_claims_for_question,
)
from app.schemas.evidence import AnswerStatus, Claim, Conflict

_STOP = frozenset(
    {
        "what",
        "which",
        "when",
        "where",
        "who",
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "in",
        "on",
        "to",
        "for",
        "from",
        "with",
        "about",
        "regarding",
        "detail",
        "missing",
        "documents",
        "say",
        "note",
        "any",
    }
)


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
    # Dual-entity coverage applies to explicit comparisons (A or B / versus),
    # not bridge-style multi-hops that merely mention multiple proper names.
    if is_comparison_question(question) and len(entities) >= 2:
        covered: list[str] = []
        for ent in entities:
            for claim in supporting:
                hay = (
                    f"{claim.source_title or ''} {claim.subject} {claim.attribute} "
                    f"{claim.value} {claim.quote}"
                )
                if not claim_covers_entity(hay, ent):
                    continue
                fidelity = entity_title_fidelity(ent, claim.source_title)
                # Prefer claims from a title that faithfully names this entity so
                # a peer institution page cannot satisfy both sides of a comparison.
                if fidelity >= 0.9:
                    covered.append(ent)
                    break
                if fidelity >= 0.45 and ent.lower() in hay:
                    covered.append(ent)
                    break
        if len(covered) < 2:
            return (
                "insufficient",
                "Comparison or multi-hop question requires grounded evidence for "
                "each named entity; retrieved claims cover fewer than two entities.",
            )

    # Distinctive question terms must appear in supporting claims so unrelated
    # pages that share a single token (e.g. "identity") cannot answer
    # "missing … rollback approver identity".
    hay = " ".join(
        f"{c.source_title or ''} {c.subject} {c.value} {c.quote}" for c in supporting
    ).lower()
    multi = [p for p in q_focus.phrases if len(p.replace("-", " ").split()) >= 2]
    focus_parts: list[str] = []
    if multi:
        phrase = max(multi, key=lambda p: len(p.split()))
        focus_parts = [
            p
            for p in re.split(r"[\s\-–—]+", phrase.lower())
            if p and p not in _STOP and len(p) > 3
        ]
    used_token_fallback = False
    if len(focus_parts) < 2:
        focus_parts = [
            t for t in q_focus.tokens if t not in _STOP and len(t) >= 7
        ]
        used_token_fallback = len(focus_parts) >= 2
    if len(focus_parts) >= 2:
        phrase_hits = sum(1 for p in focus_parts if p in hay)
        missing_detail = bool(
            re.search(
                r"\b(?:missing|unknown|not (?:stated|found|recorded)|absent)\b",
                question,
                re.I,
            )
        )
        if used_token_fallback and missing_detail:
            # Token fallback on "missing detail" questions: require ≥2 distinctive
            # hits so a single shared word (e.g. identity) cannot invent an answer.
            need = min(2, len(focus_parts))
            weak_focus = phrase_hits < need
        elif not used_token_fallback:
            weak_focus = phrase_hits / len(focus_parts) < 0.5
        else:
            weak_focus = False
        if weak_focus:
            return (
                "insufficient",
                "Retrieved claims do not cover the distinctive terms of the "
                "asked subject closely enough to support an answer.",
            )

    # Explicit incomplete / redacted slots (e.g. "Approver: [REDACTED]") mean the
    # asked identity is not available even if topic words overlap.
    if re.search(r"\b(?:approver|who approved|who authorized)\b", question, re.I) and (
        re.search(
            r"(?:approver\s*:\s*\[?\s*REDACTED|incomplete record|\bTBD\b)",
            hay,
            re.I,
        )
        or not re.search(
            r"(?:approver\s*:\s*[A-Z][a-z]+|approved by\s+[A-Z][a-z]+)",
            hay,
        )
    ):
        return (
            "insufficient",
            "Documents mention the topic but do not name the requested approver.",
        )

    scores = [claim_support_score(c, q_focus) for c in supporting]
    best = max(scores) if scores else 0.0
    if multi and best < 0.75 and len(entities) < 2:
        return (
            "partial",
            "Evidence partially overlaps the question but does not clearly "
            "cover the primary named subject or requested fact.",
        )

    return "answered", None
