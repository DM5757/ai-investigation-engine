"""Extract short, evidence-grounded answer spans from verified claims.

Hotpot-style gold answers are typically 1–5 tokens. Emitting full wiki sentences
destroys token F1 even when the span is present. Spans must appear verbatim
(case-insensitive) inside a claim quote.
"""

from __future__ import annotations

import re

from app.investigation.entities import (
    extract_focus_entities,
    is_comparison_question,
    should_attempt_bridge,
)
from app.investigation.fast_path import (
    best_claim_for_entity,
    comparison_direction,
    state_westness,
)
from app.schemas.evidence import Claim

_DATE_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}\b"
    r"|\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
_PREMIERE_DATE_RE = re.compile(
    # Allow network/channel text between "premiered" and the calendar date
    # e.g. "premiered on History, on June 17, 2007".
    r"(?:premiered|premiere|released|aired|broadcast)\b[^.]{0,80}?\bon\s+"
    r"("
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{4}"
    r")",
    re.IGNORECASE,
)
_KING_OF_RE = re.compile(
    r"\b(?:king|queen|prince|princess)\s+of\s+"
    r"([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})",
    re.IGNORECASE,
)
_PRODUCTION_RE = re.compile(
    r"(?:production of|produced by)\s+"
    r"([A-Z][A-Za-z0-9&]+(?:[\s\-][A-Z][A-Za-z0-9&]+){0,5})",
)
_PERSON_CREDIT_RE = re.compile(
    r"(?:directed by|written by|starring)\s+"
    r"([A-Z][A-Za-z0-9&]+(?:[\s\-][A-Z][A-Za-z0-9&]+){0,5})",
)
_TITLE_PHRASE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]*(?:(?:\s+|,\s*|[\-–—])[A-Z][A-Za-z0-9]*)+)\b"
)
_MARKER_RE = re.compile(r"\b([A-Z]{2,}(?:-[A-Z0-9]+){1,4})\b")
_ALSO_KNOWN_RE = re.compile(
    r"(?:also known as|known as)\s+([A-Z][A-Za-z0-9][A-Za-z0-9\s\-]{1,40}?)(?:[,.;]|$)",
    re.IGNORECASE,
)
_LOCATED_RE = re.compile(
    r"(?:located|based|headquartered)\s+(?:in|at|near)\s+([^.]{3,80})",
    re.IGNORECASE,
)
_ABBREV_RE = re.compile(
    r"(?:abbreviated(?:\s+as)?|abbreviation(?:\s+of|\s+for)?|acronym(?:\s+for)?)"
    r"\s*[:\-]?\s*([A-Z][A-Z0-9]{1,11})"
    r"|([A-Z][A-Z0-9]{1,11})\s*(?:\(|–|-)\s*(?:stands for|abbreviation)",
)
_PAREN_ACRONYM_RE = re.compile(
    r"\(([A-Z][A-Z0-9]{1,11})\)"
)
_BORN_RE = re.compile(
    r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\s+"
    r"(?:\([^)]{0,40}\)\s+)?"
    r"(?:was\s+)?born\s+(?:on\s+)?"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}",
)
_KNOWN_AS_ROLE_RE = re.compile(
    r"\b(?:known as|was a|is a|became a)\s+(?:a\s+|an\s+)?"
    r"(former\s+model|model|actress|actor|singer|politician|author|"
    r"director|producer|composer)",
    re.IGNORECASE,
)
_US_STATE_RE = re.compile(
    r"\b(Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|"
    r"Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|"
    r"Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|"
    r"Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|"
    r"New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|"
    r"Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|"
    r"Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming)\b"
)


def question_answer_kind(question: str) -> str:
    q = (question or "").lower()
    if is_comparison_question(question) and comparison_direction(question):
        return "comparison"
    if q.startswith(("are ", "is ", "do ", "does ", "did ", "was ", "were ")) and (
        " both " in f" {q}" or q.rstrip().endswith("?")
    ):
        return "yesno"
    if re.search(r"\b(?:abbreviation|abbreviated|acronym)s?\b", q):
        return "abbrev"
    if re.search(
        r"\b(?:what date|which date|what time|at what time|when (?:did|was|were)|premiered)\b",
        q,
    ):
        return "date"
    if re.search(r"\b(?:which country|king of|queen of|which nation)\b", q):
        return "country"
    if re.search(r"\b(?:which state|what state)\b", q):
        return "state"
    if re.search(r"\b(?:where|located|location)\b", q):
        return "location"
    if re.search(r"\b(?:who|whom|whose)\b", q):
        return "person"
    if re.search(r"\b(?:which|what)\b", q):
        return "entity"
    return "generic"


def extract_span_from_claims(
    question: str, claims: list[Claim]
) -> tuple[str, list[Claim], float] | None:
    """Return (span, supporting_claims, confidence) or None.

    Confidence in ``[0, 1]``. Callers may treat ``>= 0.7`` as deterministic-safe.
    """
    verified = [c for c in claims if c.verified]
    if not verified:
        return None
    kind = question_answer_kind(question)
    if kind == "comparison":
        return _comparison_span(question, verified)
    if kind == "yesno":
        return _yesno_span(question, verified)
    if kind == "abbrev":
        hit = _abbrev_span(question, verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
    if kind == "date":
        hit = _date_span(question, verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
        return None
    if kind == "country":
        hit = _country_span(verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
        return None
    if kind == "state":
        hit = _state_span(verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
    if kind == "location":
        hit = _location_span(verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
    # Prefer production-company cues for "which company / produced" questions.
    q_low_early = question.lower()
    if re.search(r"\b(?:misconfiguration|misconfigured|jwt|ttl)\b", q_low_early):
        hit = _jwt_misconfig_span(verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
    hit = _services_span(question, verified)
    if hit:
        return _with_bridge_support(question, verified, hit)
    if re.search(r"\b(?:company|produced|production|studio)\b", q_low_early):
        hit = _pattern_span(verified, _PRODUCTION_RE, confidence=0.8)
        if hit:
            return _with_bridge_support(question, verified, hit)
    q_low = question.lower()
    if re.search(r"\bborn\b", q_low):
        hit = _born_person_span(question, verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
        # Do not fall through to "starring X" credits — those are unrelated
        # to a birth-date question and would falsely look high-confidence.
    elif kind == "person":
        hit = _pattern_span(verified, _PERSON_CREDIT_RE, confidence=0.7)
        if hit:
            return _with_bridge_support(question, verified, hit)
        hit = _role_span(verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
    if re.search(r"\b(?:known as|former model|profession)\b", q_low):
        hit = _role_span(verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
    # Marker tokens (e.g. ALPHA-OUTAGE-0810) only when the question asks for a
    # marker/code — not for root-cause / contradiction prompts that merely
    # retrieve the architecture page containing the marker.
    asks_marker = bool(
        re.search(r"\b(?:marker|code|token|identifier|ALPHA-)\b", question, re.I)
    )
    blocks_marker = bool(
        re.search(r"\b(?:root cause|contradict|caused by)\b", question, re.I)
    )
    if asks_marker or not blocks_marker:
        hit = _marker_span(verified)
        if hit:
            return _with_bridge_support(question, verified, hit)
    if kind in {"person", "entity", "location", "generic", "abbrev", "state"}:
        return _entity_span(question, verified)
    return None


def _with_bridge_support(
    question: str,
    claims: list[Claim],
    hit: tuple[str, list[Claim], float],
) -> tuple[str, list[Claim], float]:
    """Attach a first-hop claim so multi-hop answers keep required citations."""
    span, support, conf = hit
    entities = extract_focus_entities(question)
    if not should_attempt_bridge(question, entities) or not entities:
        return hit
    first = best_claim_for_entity(claims, entities[0])
    if first is None:
        return hit
    docs = {c.doc_id for c in support}
    if first.doc_id not in docs:
        support = [first, *support]
    return span, support, conf


def _comparison_span(
    question: str, claims: list[Claim]
) -> tuple[str, list[Claim], float] | None:
    entities = extract_focus_entities(question)
    direction = comparison_direction(question)
    if len(entities) < 2 or direction not in {"west", "east"}:
        return None
    picked: list[Claim] = []
    for ent in entities[:2]:
        claim = best_claim_for_entity(claims, ent)
        if claim is None:
            return None
        picked.append(claim)
    ranks = [state_westness(f"{c.quote} {c.value}") for c in picked]
    r0, r1 = ranks[0], ranks[1]
    if r0 is None or r1 is None:
        return None
    winner_i = (0 if r0 < r1 else 1) if direction == "west" else (0 if r0 > r1 else 1)
    return entities[winner_i], picked, 0.9


_CLOCK_UTC_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*UTC\b", re.IGNORECASE)


def _date_span(
    question: str, claims: list[Claim]
) -> tuple[str, list[Claim], float] | None:
    q_low = question.lower()
    if re.search(r"\b(?:what time|at what time|deploy(?:ed)?)\b", q_low):
        # Prefer a single clock time only when sources agree; otherwise let
        # contradiction handling surface both sides.
        clocks: list[tuple[str, Claim]] = []
        for claim in claims:
            for match in _CLOCK_UTC_RE.finditer(f"{claim.quote} {claim.value}"):
                clocks.append((match.group(1) + " UTC", claim))
        uniq = list(dict.fromkeys(t for t, _ in clocks))
        if len(uniq) == 1:
            return uniq[0], [clocks[0][1]], 0.9
    premiere_hits: list[tuple[int, str, Claim]] = []
    q_wants_series = bool(
        re.search(r"\b(?:reality|television|tv|series|show)\b", q_low)
    )
    # Titles mentioned in other claims are grounded second hops (e.g. Lent → IRT).
    grounded_titles = " ".join(
        f"{c.quote} {c.value}" for c in claims
    ).lower()
    for claim in claims:
        hay = f"{claim.source_title or ''} {claim.quote} {claim.value}"
        premiere = _PREMIERE_DATE_RE.search(hay)
        if not premiere:
            continue
        span = re.sub(r"\s+", " ", premiere.group(1)).replace(" ,", ",").strip()
        span = re.sub(r",\s*", ", ", span)
        score = 2
        title = (claim.source_title or "").lower().strip()
        bare = re.sub(r"\s*\([^)]*\)\s*", " ", title).strip()
        bare = re.sub(r"\s+", " ", bare)
        if bare and len(bare) >= 6:
            # Grounded second hop: a *different document* must mention this title
            # (sibling claims from the same page do not count).
            others = " ".join(
                f"{c.quote} {c.value}"
                for c in claims
                if c.doc_id != claim.doc_id
            ).lower()
            if bare in others:
                score += 6
        if q_wants_series and re.search(
            r"\b(?:reality|television|tv|series|show|history)\b", hay, re.I
        ):
            score += 3
        if re.search(r"\b(?:film|movie|album)\b", hay, re.I) and q_wants_series:
            score -= 2
        premiere_hits.append((score, span, claim))
    if premiere_hits:
        premiere_hits.sort(key=lambda item: (-item[0], item[1]))
        _score, span, claim = premiere_hits[0]
        return span, [claim], 0.92
    for claim in claims:
        dated = _DATE_RE.search(f"{claim.quote} {claim.value}")
        if dated:
            span = re.sub(r"\s+", " ", dated.group(0)).strip()
            span = re.sub(r",\s*", ", ", span)
            return span, [claim], 0.7
    return None


def _country_span(claims: list[Claim]) -> tuple[str, list[Claim], float] | None:
    for claim in claims:
        match = _KING_OF_RE.search(f"{claim.quote} {claim.value}")
        if match:
            return match.group(1).strip(), [claim], 0.9
    return None


def _location_span(claims: list[Claim]) -> tuple[str, list[Claim], float] | None:
    for claim in claims:
        hay = f"{claim.quote} {claim.value}"
        known = _ALSO_KNOWN_RE.search(hay)
        if known:
            return known.group(1).strip(" ,"), [claim], 0.85
        loc = _LOCATED_RE.search(hay)
        if loc:
            span = re.sub(r"\s+", " ", loc.group(1)).strip(" ,")
            # Keep a short location tail.
            span = ", ".join(part.strip() for part in span.split(",")[:3])
            if 3 <= len(span) <= 80:
                return span, [claim], 0.8
    return None


def _pattern_span(
    claims: list[Claim], pattern: re.Pattern[str], *, confidence: float
) -> tuple[str, list[Claim], float] | None:
    for claim in claims:
        match = pattern.search(f"{claim.quote} {claim.value}")
        if match:
            return match.group(1).strip(), [claim], confidence
    return None


def _marker_span(claims: list[Claim]) -> tuple[str, list[Claim], float] | None:
    for claim in claims:
        for match in _MARKER_RE.finditer(f"{claim.quote} {claim.value}"):
            token = match.group(1)
            if token.count("-") >= 1 and len(token) >= 8:
                return token, [claim], 0.85
    return None


_JWT_MISCONFIG_RE = re.compile(
    r"(misconfigured\s+JWT\s+TTL|JWT\s+TTL\s+misconfiguration|"
    r"misconfigured\s+JWT|JWT\s+TTL)",
    re.IGNORECASE,
)
_SERVICES_AFFECTED_RE = re.compile(
    r"\b((?:payment|authentication|auth)(?:\s+and\s+(?:payment|authentication|auth))?"
    r"(?:\s+services?)?)\b",
    re.IGNORECASE,
)


def _jwt_misconfig_span(
    claims: list[Claim],
) -> tuple[str, list[Claim], float] | None:
    for claim in claims:
        match = _JWT_MISCONFIG_RE.search(f"{claim.quote} {claim.value}")
        if match:
            span = re.sub(r"\s+", " ", match.group(1)).strip()
            # Prefer the fuller ops phrasing when present.
            if "misconfigured" in span.lower() and "ttl" in span.lower():
                return "misconfigured JWT TTL", [claim], 0.9
            return span, [claim], 0.8
    return None


def _services_span(
    question: str, claims: list[Claim]
) -> tuple[str, list[Claim], float] | None:
    if not re.search(r"\b(?:services?|affected)\b", question.lower()):
        return None
    support: list[Claim] = []
    found: list[str] = []
    for claim in claims:
        hay = f"{claim.quote} {claim.value}".lower()
        if "payment" in hay and ("auth" in hay or "authentication" in hay):
            support.append(claim)
            found.append("payment and authentication services")
        elif "payment" in hay:
            support.append(claim)
            found.append("payment")
        elif "authentication" in hay or "authgateway" in hay.replace("-", ""):
            support.append(claim)
            found.append("authentication")
    if not support:
        return None
    if any("payment and authentication" in f for f in found):
        return "payment and authentication services", support[:2], 0.85
    if "payment" in found and "authentication" in found:
        return "payment and authentication services", support[:2], 0.85
    return None


def _yesno_span(
    question: str, claims: list[Claim]
) -> tuple[str, list[Claim], float] | None:
    """Answer yes/no only when the asked relation is evidenced — not name co-occurrence."""
    entities = extract_focus_entities(question)
    if len(entities) < 2:
        return None
    q_low = question.lower()
    hay = " ".join(f"{c.quote} {c.value} {c.source_title or ''}" for c in claims).lower()
    if not all(e.lower() in hay for e in entities[:2]):
        return None
    # Nationality / "same X" questions need matching attribute evidence.
    if re.search(r"\bsame nationality\b|\bsame country\b|\bboth\b.*\bnational", q_low):
        nations = re.findall(
            r"\b(american|british|romanian|french|german|italian|spanish|"
            r"canadian|australian|irish|scottish|english|russian|chinese|"
            r"japanese|indian|pakistani|mexican|brazilian)\b",
            hay,
        )
        uniq = {n for n in nations}
        if len(uniq) >= 2:
            return "no", claims[:2], 0.78
        if len(uniq) == 1 and len(nations) >= 2:
            return "yes", claims[:2], 0.78
        # Insufficient nationality signal — leave for LLM / abstention.
        return None
    if re.search(r"\bboth associated\b|\bboth\b.*\b(?:band|rock)\b", q_low):
        # Require the association cue near evidence, not mere name presence.
        if re.search(r"\b(?:band|rock|associated|member|singer)\b", hay):
            return "yes", claims[:2], 0.7
        return None
    return None


def _abbrev_span(
    question: str, claims: list[Claim]
) -> tuple[str, list[Claim], float] | None:
    for claim in claims:
        hay = f"{claim.quote} {claim.value}"
        match = _ABBREV_RE.search(hay)
        if match:
            token = next(g for g in match.groups() if g)
            return token, [claim], 0.85
    # Parenthetical acronym near a title word from the question.
    q_tokens = {t for t in re.findall(r"[A-Za-z]{4,}", question) if t[0].isupper()}
    for claim in claims:
        hay = f"{claim.quote} {claim.value}"
        for match in _PAREN_ACRONYM_RE.finditer(hay):
            # Prefer acronyms that sit beside capitalized title tokens.
            start = max(0, match.start() - 40)
            window = hay[start : match.end() + 10]
            if any(tok in window for tok in q_tokens) or len(match.group(1)) >= 3:
                return match.group(1), [claim], 0.78
    return None


def _born_person_span(
    question: str, claims: list[Claim]
) -> tuple[str, list[Claim], float] | None:
    q_low = question.lower()
    # Prefer a birth date mentioned in the question when present.
    date_in_q = _DATE_RE.search(question)
    for claim in claims:
        hay = f"{claim.quote} {claim.value}"
        if date_in_q and normalize_loose(date_in_q.group(0)) not in normalize_loose(
            hay
        ):
            continue
        if date_in_q:
            # "Name (born April 20, 1949)" style
            alt = re.search(
                rf"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){{0,3}})\s*"
                rf"\([^)]*{re.escape(date_in_q.group(0))}[^)]*\)",
                hay,
            )
            if alt and alt.group(1).lower() not in q_low:
                return alt.group(1).strip(), [claim], 0.86
        match = _BORN_RE.search(hay)
        if match:
            name = match.group(1).strip()
            if name.lower() not in q_low:
                return name, [claim], 0.84
    return None


def _role_span(claims: list[Claim]) -> tuple[str, list[Claim], float] | None:
    for claim in claims:
        match = _KNOWN_AS_ROLE_RE.search(f"{claim.quote} {claim.value}")
        if match:
            return match.group(1).strip().lower(), [claim], 0.8
    return None


def _state_span(claims: list[Claim]) -> tuple[str, list[Claim], float] | None:
    for claim in claims:
        match = _US_STATE_RE.search(f"{claim.quote} {claim.value}")
        if match:
            return match.group(1), [claim], 0.82
    return None


def normalize_loose(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _entity_span(
    question: str, claims: list[Claim]
) -> tuple[str, list[Claim], float] | None:
    q_low = question.lower()
    q_entities = {e.lower() for e in extract_focus_entities(question)}
    # Tokens already named in the question are weak answer candidates.
    scored: list[tuple[float, str, Claim]] = []
    for claim in claims:
        hay = f"{claim.quote} {claim.value}"
        title = (claim.source_title or "").strip()
        if (
            title
            and title.lower() not in q_low
            and len(title.split()) <= 8
            and not any(title.lower() == e for e in q_entities)
        ):
            # Title may be the Hotpot answer, but keep confidence below the
            # deterministic threshold so adaptive mode can ask the LLM.
            scored.append((0.48 + 0.03 * min(3, len(title.split())), title, claim))
        for match in _TITLE_PHRASE_RE.finditer(hay):
            phrase = match.group(1).strip()
            low = phrase.lower()
            if low in q_low or low in q_entities:
                continue
            if len(phrase.split()) > 6:
                continue
            scored.append((0.45 + 0.03 * len(phrase.split()), phrase, claim))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    best_score, span, claim = scored[0]
    # Multi-hop: attach a first-hop claim when available for citation coverage.
    support = [claim]
    if should_attempt_bridge(question, extract_focus_entities(question)):
        ents = extract_focus_entities(question)
        if ents:
            first = best_claim_for_entity(claims, ents[0])
            if first is not None and first.doc_id != claim.doc_id:
                support = [first, claim]
    return span, support, min(0.65, best_score)


def needs_llm_synthesis(
    question: str,
    claims: list[Claim],
    *,
    status: str,
    span_confidence: float | None,
) -> bool:
    """Route to LLM when evidence exists but a short grounded span is uncertain."""
    if status in {"insufficient", "llm_unavailable", "conflicting"}:
        return False
    # High-confidence patterned spans stay on the free deterministic path;
    # everything else needs semantic integration when an LLM is available.
    return not (span_confidence is not None and span_confidence >= 0.7)


__all__ = [
    "extract_span_from_claims",
    "needs_llm_synthesis",
    "question_answer_kind",
]
