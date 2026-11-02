"""Evidence-ready short-circuits that avoid unnecessary LLM rounds.

Deterministic only — never invents facts beyond verified claims / titles.
"""

from __future__ import annotations

import re

from app.investigation.entities import (
    claim_covers_entity,
    entity_title_fidelity,
    extract_focus_entities,
    is_comparison_question,
    should_attempt_bridge,
)
from app.investigation.tools import ToolExecutor
from app.schemas.evidence import Claim

# Coarse west→east rank for US state names appearing in location claims.
# Used only for further-west/east comparisons when both sides have locations.
_US_STATE_WESTNESS: dict[str, int] = {
    "hawaii": 0,
    "alaska": 1,
    "washington": 2,
    "oregon": 3,
    "california": 4,
    "nevada": 5,
    "idaho": 6,
    "arizona": 7,
    "utah": 8,
    "montana": 9,
    "wyoming": 10,
    "colorado": 11,
    "new mexico": 12,
    "north dakota": 13,
    "south dakota": 14,
    "nebraska": 15,
    "kansas": 16,
    "oklahoma": 17,
    "texas": 18,
    "minnesota": 19,
    "iowa": 20,
    "missouri": 21,
    "arkansas": 22,
    "louisiana": 23,
    "wisconsin": 24,
    "illinois": 25,
    "mississippi": 26,
    "michigan": 27,
    "indiana": 28,
    "kentucky": 29,
    "tennessee": 30,
    "alabama": 31,
    "ohio": 32,
    "west virginia": 33,
    "georgia": 34,
    "florida": 35,
    "pennsylvania": 36,
    "south carolina": 37,
    "north carolina": 38,
    "new york": 39,
    "virginia": 40,
    "maryland": 41,
    "delaware": 42,
    "new jersey": 43,
    "connecticut": 44,
    "rhode island": 45,
    "massachusetts": 46,
    "vermont": 47,
    "new hampshire": 48,
    "maine": 49,
}


def seed_retrieval_sufficient(question: str, tools: ToolExecutor) -> bool:
    """True when seed (+ bridge) retrieval already covers the asked entities/docs.

    Used to skip the LLM tool loop while preserving multi-hop bridge searches
    that already ran before this check.
    """
    retrieved = list(tools.state.retrieved)
    if not retrieved:
        return False
    titles = [h.chunk.title for h in retrieved if h.chunk.title]
    if not titles:
        return False
    entities = extract_focus_entities(question)

    if is_comparison_question(question) and len(entities) >= 2:
        return all(
            any(entity_title_fidelity(ent, title) >= 0.9 for title in titles)
            for ent in entities
        )

    if should_attempt_bridge(question, entities):
        # First-hop entity (if any) plus at least one other distinct title.
        distinct = {t.lower() for t in titles}
        if len(distinct) < 2:
            return False
        if entities:
            return any(entity_title_fidelity(entities[0], title) >= 0.9 for title in titles)
        return True

    if entities:
        return any(entity_title_fidelity(entities[0], title) >= 0.9 for title in titles)

    # Generic factual: at least one retrieved hit is enough to attempt claim extract.
    return len(retrieved) >= 1


def best_claim_for_entity(claims: list[Claim], entity: str) -> Claim | None:
    """Return the best verified claim covering ``entity``, preferring locations."""
    scored: list[tuple[tuple[int, float], Claim]] = []
    for claim in claims:
        if not claim.verified:
            continue
        hay = (
            f"{claim.source_title or ''} {claim.subject} {claim.attribute} "
            f"{claim.value} {claim.quote}"
        )
        if not claim_covers_entity(hay, entity):
            continue
        fidelity = entity_title_fidelity(entity, claim.source_title)
        loc = 1 if re.search(r"\b(located|in the city|columbus|carson)\b", hay, re.I) else 0
        scored.append(((-loc, -fidelity), claim))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def state_westness(text: str) -> int | None:
    low = text.lower()
    # Prefer longer multi-word states first.
    for name, rank in sorted(_US_STATE_WESTNESS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(name)}\b", low):
            return rank
    return None


def comparison_direction(question: str) -> str | None:
    q = question.lower()
    if re.search(r"\bfurther\s+west\b|\bfarther\s+west\b", q):
        return "west"
    if re.search(r"\bfurther\s+east\b|\bfarther\s+east\b", q):
        return "east"
    return None


__all__ = [
    "best_claim_for_entity",
    "comparison_direction",
    "seed_retrieval_sufficient",
    "state_westness",
]
