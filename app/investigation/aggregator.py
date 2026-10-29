"""Aggregate verified claims by (subject, attribute); collapse near-dups."""

from __future__ import annotations

from collections import defaultdict

from app.schemas.evidence import Claim


def _norm_key(text: str) -> str:
    return " ".join(text.lower().split())


def _independent_docs(claims: list[Claim]) -> list[Claim]:
    """Keep one claim per (doc_id, normalized value) within a group."""
    seen: set[tuple[str, str]] = set()
    out: list[Claim] = []
    for claim in claims:
        key = (claim.doc_id, _norm_key(claim.value))
        if key in seen:
            continue
        seen.add(key)
        out.append(claim)
    return out


def assign_source_labels(claims: list[Claim]) -> list[Claim]:
    """Assign stable [S1], [S2], … labels by first-seen order."""
    labeled: list[Claim] = []
    for i, claim in enumerate(claims, start=1):
        labeled.append(claim.model_copy(update={"source_label": f"S{i}"}))
    return labeled


def aggregate_claims(claims: list[Claim]) -> dict[tuple[str, str], list[Claim]]:
    """Group verified claims by normalized (subject, attribute)."""
    groups: dict[tuple[str, str], list[Claim]] = defaultdict(list)
    for claim in claims:
        if not claim.verified:
            continue
        key = (_norm_key(claim.subject), _norm_key(claim.attribute))
        groups[key].append(claim)
    return {k: _independent_docs(v) for k, v in groups.items()}
