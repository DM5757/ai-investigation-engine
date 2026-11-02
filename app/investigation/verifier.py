"""Citation verification against labeled claims; strip fabricated refs."""

from __future__ import annotations

from app.investigation.citations import (
    extract_citation_labels,
    find_malformed_citations,
    strip_disallowed_citations,
)
from app.schemas.evidence import AnswerStatus, Citation, Claim


def allowed_labels(citations: list[Citation]) -> set[str]:
    return {c.label for c in citations}


def strip_fabricated_citations(answer: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Remove citation markers that are not in ``allowed``; return cleaned + removed."""
    return strip_disallowed_citations(answer, allowed)


def verify_answer_citations(
    answer: str | None,
    citations: list[Citation],
    claims: list[Claim],
) -> tuple[str | None, list[Citation], list[str], bool]:
    """
    Verify citation labels appear in the claim/citation set.

    Detects grouped markers ([S1, S2]), Unicode/invisible variants, and
    malformed citation-like tokens. Invented labels are stripped, not ignored.

    Returns (answer, citations, removed_labels, ok).
    """
    if not answer:
        return answer, citations, [], True
    allowed = allowed_labels(citations)
    for claim in claims:
        if claim.source_label:
            allowed.add(claim.source_label)
    used = extract_citation_labels(answer)
    malformed = find_malformed_citations(answer)
    fabricated = sorted(used - allowed)
    if not fabricated and not malformed:
        return answer, citations, [], True
    cleaned, removed = strip_fabricated_citations(answer, allowed)
    # Include malformed tokens in the removed list for diagnostics.
    for m in malformed:
        if m not in removed:
            removed.append(m)
    return cleaned, citations, removed, False


def downgrade_status(status: AnswerStatus, *, citation_failed: bool) -> AnswerStatus:
    if not citation_failed:
        return status
    if status == "answered":
        return "partial"
    return status
