"""Claim extraction helpers and deterministic quote verification."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.schemas.evidence import Claim


def normalize_for_quote(text: str) -> str:
    """NFKC, lower-case, collapse whitespace for quote matching."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return " ".join(normalized.split())


def quote_appears_in_chunk(quote: str, chunk_text: str) -> bool:
    """Return True iff normalized quote is a substring of normalized chunk."""
    q = normalize_for_quote(quote)
    if len(q) < 3:
        return False
    return q in normalize_for_quote(chunk_text)


def verify_claim_quote(claim: Claim, chunk_text: str) -> Claim:
    """Return a copy of ``claim`` with ``verified`` set from quote check."""
    ok = quote_appears_in_chunk(claim.quote, chunk_text)
    return claim.model_copy(update={"verified": ok})


def claims_from_tool_payload(
    payload: dict[str, Any],
    *,
    chunk_text: str,
    chunk_id: str,
    doc_id: str,
    claim_id: str,
    source_title: str | None = None,
) -> Claim | None:
    """Build and verify a claim from a structured tool/LLM payload."""
    subject = str(payload.get("subject", "")).strip()
    attribute = str(payload.get("attribute", "")).strip()
    value = str(payload.get("value", "")).strip()
    quote = str(payload.get("quote", "")).strip()
    if not (subject and attribute and value and quote):
        return None
    title = source_title
    if title is None and isinstance(payload.get("title"), str):
        title = payload["title"]
    claim = Claim(
        claim_id=claim_id,
        subject=subject,
        attribute=attribute,
        value=value,
        quote=quote,
        chunk_id=chunk_id,
        doc_id=doc_id,
        source_title=title,
    )
    return verify_claim_quote(claim, chunk_text)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_RELATION_CUE = re.compile(
    r"\b("
    r"located|location|based|headquartered|founded|born|died|premiered|"
    r"nicknamed|nickname|known as|daughter of|son of|star of|star on|"
    r"co-writer|west|east|north|south|city of|county|country|date|in the|"
    r"king of|queen of|role as"
    r")\b",
    re.IGNORECASE,
)


def heuristic_claims_from_chunk(
    *,
    chunk_id: str,
    doc_id: str,
    text: str,
    subject_hint: str,
    claim_prefix: str,
    source_title: str | None = None,
) -> list[Claim]:
    """Deterministic fallback: subject-mention sentences plus anaphoric follow-ons.

    Wiki-style abstracts often name an entity in sentence 1 and put the asked
    fact (location, premiere date, parentage) in sentence 2 with ``It``/``The``.
    Capture that continuation when it carries a relational cue.
    """
    claims: list[Claim] = []
    hint = subject_hint.lower().strip()
    title_l = (source_title or "").lower().strip()
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    selected: list[tuple[int, str]] = []
    for i, s in enumerate(sentences):
        if len(s) < 20 or len(s) > 320:
            continue
        low = s.lower()
        mentions = bool(hint and hint in low) or bool(title_l and title_l in low)
        if mentions:
            selected.append((i, s))
            # Anaphoric continuation: the next 1–2 sentences often hold the
            # asked fact after a wiki-style entity intro.
            for j in (i + 1, i + 2):
                if j >= len(sentences):
                    break
                nxt = sentences[j]
                if 20 <= len(nxt) <= 320 and _RELATION_CUE.search(nxt):
                    selected.append((j, nxt))
            continue
        # Title-aligned chunks: keep strongly relational sentences even when the
        # entity name is elided (``It is located in Carson, California``).
        if (
            title_l
            and hint
            and (hint in title_l or title_l in hint)
            and _RELATION_CUE.search(s)
        ):
            selected.append((i, s))

    seen_i: set[int] = set()
    for i, s in selected:
        if i in seen_i:
            continue
        seen_i.add(i)
        quote = s[:240]
        claim = Claim(
            claim_id=f"{claim_prefix}-{i}",
            subject=subject_hint or source_title or doc_id,
            attribute="statement",
            value=s[:200],
            quote=quote,
            chunk_id=chunk_id,
            doc_id=doc_id,
            source_title=source_title,
        )
        verified = verify_claim_quote(claim, text)
        if verified.verified:
            claims.append(verified)
    return claims[:5]
