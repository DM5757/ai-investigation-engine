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


_SINGLE_NAME_RE = re.compile(r"\b([A-Z][a-zA-Z]{4,})\b")
_BRIDGE_STOP = frozenset(
    {
        "which",
        "where",
        "whose",
        "after",
        "before",
        "during",
        "about",
        "there",
        "these",
        "those",
        "their",
        "other",
        "based",
        "known",
        "called",
        "university",
        "state",
        "college",
        "school",
        "county",
        "country",
        "series",
        "character",
        "daughter",
        "memoirs",
        "writer",
        "producer",
        "shakespeare",
    }
)


def extract_title_phrases(text: str, *, max_phrases: int = 12) -> list[str]:
    """Extract title-case phrases and distinctive single CapWords from text."""
    found: list[str] = []
    for match in _TITLE_PHRASE_RE.finditer(text or ""):
        cleaned = _clean_entity_span(match.group(1))
        if cleaned:
            found.append(cleaned)
    for match in _SINGLE_NAME_RE.finditer(text or ""):
        name = match.group(1)
        if name.lower() in _STOP or name.lower() in _BRIDGE_STOP:
            continue
        found.append(name)
    return _dedupe(found)[:max_phrases]


_MULTI_HOP_CUES = re.compile(
    r"\b(?:nicknamed|nickname|premiered|co-writer|cowriter|daughter of|son of|"
    r"star on|star of|further (?:west|east|north|south)|compared|versus|"
    r"which country|which date|what date)\b",
    re.IGNORECASE,
)
_BRIDGE_LINK_CUES = re.compile(
    r"(?:nicknamed|named|called|known as|star of|star on|series|title|"
    r"daughter of|son of|premiered|written by|co-writer|memoirs of)\s+"
    r"(.{0,60})",
    re.IGNORECASE,
)


def should_attempt_bridge(question: str, entities: list[str]) -> bool:
    """Bridge hops only for comparison/multi-hop style questions."""
    if len(entities) >= 2:
        return True
    return bool(_MULTI_HOP_CUES.search(question or ""))


def bridge_entity_queries(
    *,
    question: str,
    retrieved_titles: list[str],
    retrieved_texts: list[str],
    known_entities: list[str],
    max_bridges: int = 2,
) -> list[str]:
    """Propose follow-up searches for entities mentioned in evidence but not retrieved.

    Supports multi-hop jumps (nickname → character title, memoir subject → show title)
    without hardcoding particular documents. Candidates must appear near a relational
    cue or share a content token with the question to avoid topical drift.
    """
    if not should_attempt_bridge(question, known_entities):
        return []

    known: set[str] = {e.lower() for e in known_entities}
    known.update(t.lower() for t in retrieved_titles if t)
    known.update(p.lower() for p in extract_title_phrases(question))
    q_low = question.lower()
    q_tokens = {
        t
        for t in re.findall(r"[a-z][a-z0-9_-]{3,}", q_low)
        if t not in _STOP and t not in _BRIDGE_STOP
    }

    scores: dict[str, float] = {}
    for text in retrieved_texts:
        window = text[:1400]
        linked: set[str] = set()
        for match in _BRIDGE_LINK_CUES.finditer(window):
            for phrase in extract_title_phrases(match.group(0)):
                linked.add(phrase.lower())

        for phrase in extract_title_phrases(window):
            key = phrase.lower()
            if key in known or key in q_low:
                continue
            parts = [
                p
                for p in re.split(r"[\s\-–,，]+", key)
                if p and p not in _STOP and len(p) > 2
            ]
            shares_question = bool(q_tokens & set(parts))
            if key not in linked and not shares_question:
                continue
            scores[phrase] = scores.get(phrase, 0.0) + (
                1.5 if key in linked else 1.0
            ) + 0.15 * len(phrase.split())

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return [p for p, _ in ranked[:max_bridges]]


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
    "bridge_entity_queries",
    "claim_covers_entity",
    "entity_title_fidelity",
    "extract_focus_entities",
    "extract_title_phrases",
    "should_attempt_bridge",
]
