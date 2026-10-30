"""Question-conditioned focus terms for sufficiency and claim filtering.

Generic helpers only — no dataset- or entity-specific hardcoding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.evidence import Claim

_STOP = frozenset(
    {
        "what",
        "which",
        "when",
        "where",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "does",
        "did",
        "were",
        "was",
        "are",
        "is",
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
        "about",
        "into",
        "over",
        "after",
        "before",
        "between",
        "that",
        "this",
        "these",
        "those",
        "there",
        "their",
        "have",
        "has",
        "had",
        "been",
        "being",
        "also",
        "known",
        "called",
        "according",
        "across",
        "during",
        "caused",
        "cause",
        "please",
        "explain",
        "describe",
        "tell",
        "give",
        "located",
        "location",
        "disappearance",
        "disappeared",
        "happen",
        "happened",
        "information",
    }
)

# Title-case multi-token entities, including comma-titles.
_PHRASE_TITLE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]*(?:(?:\s+|,\s*|[\-–—])[A-Z][A-Za-z0-9]*)+)\b"
)
# Mixed-case two-token entities: "Roanoke colony" (not whole questions).
_PHRASE_MIXED_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]+[\s\-–—][a-z][A-Za-z0-9]{2,})\b"
)
_QUESTION_STARTERS = frozenset(
    {
        "which",
        "what",
        "when",
        "where",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "is",
        "are",
        "was",
        "were",
        "does",
        "did",
        "do",
        "can",
        "could",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_QUOTE_RE = re.compile(r"[\"“”']([^\"“”']{3,80})[\"“”']")


@dataclass(frozen=True)
class QuestionFocus:
    """Salient phrases and tokens extracted from a natural-language question."""

    phrases: tuple[str, ...]
    tokens: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not self.phrases and not self.tokens


def extract_question_focus(question: str) -> QuestionFocus:
    """Pull multi-token proper phrases and content tokens from ``question``."""
    from app.investigation.entities import extract_focus_entities

    phrases: list[str] = []
    # Multi-hop / comparison entities first (handles comma-titles and "A or B").
    phrases.extend(extract_focus_entities(question))
    for match in _QUOTE_RE.finditer(question):
        phrases.append(_norm_phrase(match.group(1)))
    for match in _PHRASE_TITLE_RE.finditer(question):
        phrases.append(_norm_phrase(match.group(1)))
    for match in _PHRASE_MIXED_RE.finditer(question):
        raw = _norm_phrase(match.group(1))
        first = re.split(r"[\s\-–—]+", raw)[0]
        # Skip CamelCase/PascalCase heads (PaymentService disruptions) — those
        # are already covered as single tokens; mixed phrases are for
        # Title + lowercase like "Roanoke colony".
        if any(ch.isupper() for ch in first[1:]):
            continue
        phrases.append(raw)
    # Hyphen/en-dash compounds even if casing is mixed
    for match in re.finditer(
        r"\b([A-Za-z][A-Za-z0-9]*(?:[\-–—][A-Za-z][A-Za-z0-9]*){1,})\b",
        question,
    ):
        phrases.append(_norm_phrase(match.group(1)))

    uniq_phrases: list[str] = []
    seen_p: set[str] = set()
    for phrase in phrases:
        cleaned = _strip_leading_aux(phrase)
        key = cleaned.lower()
        if len(key) < 4 or key in seen_p:
            continue
        parts_all = [p for p in re.split(r"[\s\-–—]+", key) if p]
        if parts_all and parts_all[0] in _QUESTION_STARTERS:
            continue
        # Drop phrases that are only stopwords / stop-inflated (e.g. "March according")
        parts = [p for p in parts_all if p not in _STOP]
        if len(parts) < 1:
            continue
        if len(parts_all) >= 2 and len(parts) < 2:
            continue
        if len(parts) == 1 and parts[0] in _STOP:
            continue
        # Drop adverbial leftovers like "Hills further"
        if len(parts) == 2 and parts[-1] in {
            "further",
            "farther",
            "west",
            "east",
            "north",
            "south",
        }:
            continue
        seen_p.add(key)
        uniq_phrases.append(cleaned)

    tokens: list[str] = []
    seen_t: set[str] = set()
    for tok in _TOKEN_RE.findall(question):
        low = tok.lower()
        if low in _STOP or len(low) < 4:
            continue
        if low in seen_t:
            continue
        seen_t.add(low)
        tokens.append(low)

    # Prefer longer phrases first for matching
    uniq_phrases.sort(key=lambda p: (-len(p.split()), -len(p)))
    return QuestionFocus(phrases=tuple(uniq_phrases[:8]), tokens=tuple(tokens[:12]))


def _strip_leading_aux(phrase: str) -> str:
    parts = phrase.split()
    while parts and parts[0].lower().rstrip("?,.") in _QUESTION_STARTERS:
        parts = parts[1:]
    return " ".join(parts).strip()

def claim_support_score(claim: Claim, focus: QuestionFocus) -> float:
    """Return 0..1 how well a claim supports the question's subject/focus."""
    if focus.empty:
        return 0.5
    from app.investigation.entities import best_entity_fidelity

    hay = f"{claim.subject} {claim.attribute} {claim.value} {claim.quote}".lower()
    # Prefer claims grounded in titles that faithfully match focus entities
    # (exact "Ohio State University" over "Ohio State University, Mansfield Campus").
    fidelity = best_entity_fidelity(
        list(focus.phrases), claim.source_title or claim.subject
    )
    title_boost = 0.0
    if focus.phrases:
        phrase_hits = 0.0
        for phrase in focus.phrases:
            parts = [
                p
                for p in re.split(r"[\s\-–—]+", phrase.lower())
                if p and p not in _STOP and len(p) > 2
            ]
            if not parts:
                continue
            covered = sum(1 for p in parts if p in hay)
            ratio = covered / len(parts)
            # Require majority of distinctive phrase tokens for a phrase hit
            if ratio >= 0.6:
                phrase_hits = max(phrase_hits, ratio)
                if ratio >= 0.99:
                    title_boost = 0.15
        if phrase_hits >= 0.6:
            base = min(1.0, 0.55 + 0.45 * phrase_hits + title_boost)
            if fidelity >= 0.9:
                return min(1.0, base + 0.1)
            if 0 < fidelity < 0.4:
                # Extended campus/branch title for a shorter queried entity.
                return min(0.45, base * 0.55)
            return base
        # Multi-token phrase present in question but not in claim → weak at best
        if any(len(p.split()) >= 2 or "-" in p or "–" in p for p in focus.phrases):
            token_hits = _token_coverage(hay, focus.tokens)
            # Single shared token (e.g. only "roanoke") is not enough
            return min(0.35, token_hits * 0.35)

    return _token_coverage(hay, focus.tokens)

def filter_claims_for_question(
    claims: list[Claim],
    question: str,
    *,
    min_support: float = 0.55,
) -> tuple[list[Claim], list[Claim], QuestionFocus]:
    """Split claims into supporting vs weak/generic keyword-only matches."""
    focus = extract_question_focus(question)
    supporting: list[Claim] = []
    weak: list[Claim] = []
    for claim in claims:
        score = claim_support_score(claim, focus)
        if score >= min_support:
            supporting.append(claim)
        else:
            weak.append(claim)
    return supporting, weak, focus


def evidence_text_support(text: str, title: str | None, focus: QuestionFocus) -> float:
    """Score a retrieved chunk/title against question focus (for previews)."""
    fake = Claim(
        claim_id="tmp",
        subject=title or "",
        attribute="statement",
        value="",
        quote=text,
        chunk_id="tmp",
        doc_id="tmp",
        verified=True,
    )
    return claim_support_score(fake, focus)


def _token_coverage(hay: str, tokens: tuple[str, ...]) -> float:
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in hay)
    frac = hits / len(tokens)
    # A long distinctive token (named entity / technical term) is enough to
    # count as subject support even when other question tokens are absent.
    long_hits = [t for t in tokens if len(t) >= 8 and t in hay]
    if long_hits:
        return max(frac, 0.7)
    mid_hits = [t for t in tokens if len(t) >= 6 and t in hay]
    if mid_hits:
        return max(frac, 0.55)
    return frac


def _norm_phrase(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.replace("—", "-").replace("–", "-")).strip()
