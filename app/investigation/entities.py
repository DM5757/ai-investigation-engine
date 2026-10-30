"""Generic multi-entity extraction for comparison / multi-hop questions.

No dataset- or title-specific hardcoding — patterns only.
"""

from __future__ import annotations

import re

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
        "at",
        "to",
        "for",
        "from",
        "with",
        "is",
        "are",
        "was",
        "were",
        "further",
        "farther",
        "west",
        "east",
        "north",
        "south",
    }
)

# Do not split on bare "and" — it appears in ordinary multi-clause questions.
_SPLIT_RE = re.compile(
    r"\s+(?:or|versus|vs\.?|compared\s+with|compared\s+to)\s+",
    re.IGNORECASE,
)
_LEAD_AUX_RE = re.compile(
    r"^(?:is|are|was|were|does|did|do|can|could|which|what|who|"
    r"whom|whose|where|when|why|how)\s+",
    re.IGNORECASE,
)
_TRAIL_JUNK_RE = re.compile(
    r"\s+(?:further|farther|more|most|better|worse|larger|smaller|"
    r"older|newer|earlier|later|first|last|west|east|north|south|"
    r"located|located\s+in|based|known)\b.*$",
    re.IGNORECASE,
)
# Allow comma-titles ("University, Dominguez Hills") via ",\s*" not bare ",".
_TITLE_PHRASE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]*(?:(?:\s+|,\s*|[\-–—])[A-Z][A-Za-z0-9]*)+)\b"
)
_PAREN_TAIL_RE = re.compile(r"\s*\([^)]*\)\s*$")


def extract_focus_entities(question: str, *, max_entities: int = 4) -> list[str]:
    """Extract comparable named entities from a natural-language question.

    Handles patterns like ``Is A or B further west?`` and comma-containing
    titles such as ``California State University, Dominguez Hills``.
    """
    q = (question or "").strip()
    if not q:
        return []

    # Prefer explicit alternatives joined by or/versus/and.
    parts = [p.strip(" ?.") for p in _SPLIT_RE.split(q) if p.strip(" ?.")]
    entities: list[str] = []
    if len(parts) >= 2:
        for part in parts:
            ent = _clean_entity_span(part)
            if ent:
                entities.append(ent)
    if len(entities) >= 2:
        return _dedupe(entities)[:max_entities]

    # Fallback: title-case multi-token phrases in the full question.
    for match in _TITLE_PHRASE_RE.finditer(q):
        ent = _clean_entity_span(match.group(1))
        if ent:
            entities.append(ent)
    return _dedupe(entities)[:max_entities]


def entity_title_fidelity(entity: str, title: str | None) -> float:
    """Score how faithfully a document title matches a queried entity.

    Exact title wins. Longer campus/branch extensions of a shorter query entity
    are down-weighted so disambiguation prefers the named entity itself.
    """
    ent = _norm_phrase(entity).lower()
    tit = _norm_phrase(title or "").lower()
    if not ent or not tit:
        return 0.0
    if tit == ent:
        return 1.0
    # Title is a parenthetical variant of the entity.
    if _PAREN_TAIL_RE.sub("", tit).strip() == ent:
        return 0.95
    if tit.startswith(ent + ",") or tit.startswith(ent + " ("):
        return 0.2
    if tit.startswith(ent + " "):
        # Extra tokens after the entity name (campus / branch / subtitle).
        return 0.25
    if ent in tit:
        return 0.45
    # Entity tokens mostly present in title
    e_parts = [p for p in re.split(r"[\s\-–,，]+", ent) if p and p not in _STOP]
    if not e_parts:
        return 0.0
    covered = sum(1 for p in e_parts if p in tit)
    return 0.15 * (covered / len(e_parts))


def best_entity_fidelity(entities: list[str], title: str | None) -> float:
    if not entities:
        return 0.0
    return max(entity_title_fidelity(e, title) for e in entities)


def claim_covers_entity(claim_haystack: str, entity: str) -> bool:
    """True when a claim text/title supports the entity with distinctive tokens."""
    hay = claim_haystack.lower()
    ent = _norm_phrase(entity).lower()
    if ent and ent in hay:
        return True
    parts = [
        p for p in re.split(r"[\s\-–,，]+", ent) if p and p not in _STOP and len(p) > 2
    ]
    if not parts:
        return False
    # Require the longest distinctive token (avoids "State University" cross-hits).
    distinctive = sorted(parts, key=len, reverse=True)[:2]
    if not all(p in hay for p in distinctive):
        return False
    covered = sum(1 for p in parts if p in hay)
    return (covered / len(parts)) >= 0.6


def _norm_phrase(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.replace("—", "-").replace("–", "-")).strip()


def _clean_entity_span(raw: str) -> str | None:
    text = _LEAD_AUX_RE.sub("", raw.strip())
    text = _TRAIL_JUNK_RE.sub("", text).strip(" ?,.;:")
    # Keep the longest title-case phrase inside the span when present.
    matches = list(_TITLE_PHRASE_RE.finditer(text))
    if matches:
        text = max((m.group(1) for m in matches), key=lambda s: (len(s), s))
    text = _norm_phrase(text)
    if len(text) < 4:
        return None
    parts = [p for p in re.split(r"[\s\-–,，]+", text.lower()) if p]
    content = [p for p in parts if p not in _STOP]
    if len(content) < 1:
        return None
    if len(parts) >= 2 and len(content) < 2 and len(content[0]) < 8:
        return None
    return text


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    # Prefer longer entities; drop shorter ones contained in longer titles.
    out.sort(key=lambda s: (-len(s), s))
    kept: list[str] = []
    kept_l: list[str] = []
    for item in out:
        low = item.lower()
        if any(low in k and low != k for k in kept_l):
            continue
        kept.append(item)
        kept_l.append(low)
    order = {x.lower(): i for i, x in enumerate(items)}
    kept.sort(key=lambda s: order.get(s.lower(), 99))
    return kept


__all__ = [
    "best_entity_fidelity",
    "claim_covers_entity",
    "entity_title_fidelity",
    "extract_focus_entities",
]
