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
) -> Claim | None:
    """Build and verify a claim from a structured tool/LLM payload."""
    subject = str(payload.get("subject", "")).strip()
    attribute = str(payload.get("attribute", "")).strip()
    value = str(payload.get("value", "")).strip()
    quote = str(payload.get("quote", "")).strip()
    if not (subject and attribute and value and quote):
        return None
    claim = Claim(
        claim_id=claim_id,
        subject=subject,
        attribute=attribute,
        value=value,
        quote=quote,
        chunk_id=chunk_id,
        doc_id=doc_id,
    )
    return verify_claim_quote(claim, chunk_text)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def heuristic_claims_from_chunk(
    *,
    chunk_id: str,
    doc_id: str,
    text: str,
    subject_hint: str,
    claim_prefix: str,
) -> list[Claim]:
    """Deterministic fallback: treat short sentences mentioning subject as claims."""
    claims: list[Claim] = []
    hint = subject_hint.lower().strip()
    for i, sentence in enumerate(_SENTENCE_SPLIT.split(text.strip())):
        s = sentence.strip()
        if len(s) < 20 or len(s) > 280:
            continue
        if hint and hint not in s.lower():
            continue
        quote = s[:240]
        claim = Claim(
            claim_id=f"{claim_prefix}-{i}",
            subject=subject_hint or doc_id,
            attribute="statement",
            value=s[:200],
            quote=quote,
            chunk_id=chunk_id,
            doc_id=doc_id,
        )
        verified = verify_claim_quote(claim, text)
        if verified.verified:
            claims.append(verified)
    return claims[:3]
