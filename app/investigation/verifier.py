"""Citation verification against labeled claims; strip fabricated refs."""

from __future__ import annotations

import re

from app.investigation.synthesizer import citation_labels_in_text
from app.schemas.evidence import AnswerStatus, Citation, Claim

_CITE_TOKEN = re.compile(r"\[(S\d+)\]")


def allowed_labels(citations: list[Citation]) -> set[str]:
    return {c.label for c in citations}


def strip_fabricated_citations(answer: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Remove [Sn] tokens that are not in ``allowed``; return cleaned text + removed."""
    removed: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        label = match.group(1)
        if label in allowed:
            return match.group(0)
        removed.append(label)
        return ""

    cleaned = _CITE_TOKEN.sub(_repl, answer)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, removed


def verify_answer_citations(
    answer: str | None,
    citations: list[Citation],
    claims: list[Claim],
) -> tuple[str | None, list[Citation], list[str], bool]:
    """
    Verify citation labels appear in the claim set.

    Returns (answer, citations, removed_labels, ok).
    """
    if not answer:
        return answer, citations, [], True
    allowed = allowed_labels(citations)
    # Also allow labels from claims directly
    for claim in claims:
        if claim.source_label:
            allowed.add(claim.source_label)
    used = citation_labels_in_text(answer)
    fabricated = sorted(used - allowed)
    if not fabricated:
        return answer, citations, [], True
    cleaned, removed = strip_fabricated_citations(answer, allowed)
    return cleaned, citations, removed, False


def downgrade_status(status: AnswerStatus, *, citation_failed: bool) -> AnswerStatus:
    if not citation_failed:
        return status
    if status == "answered":
        return "partial"
    return status
