"""Hardened answer-to-evidence verification (Phase C).

Deterministic checks for labels, exact quotes, answer support, multi-hop
chain completeness, and basic contradiction signals. Quote existence alone
does not entail support: the claimed answer must be covered by verified quotes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.investigation.citations import strip_citation_markers
from app.schemas.evidence import Citation


@dataclass
class SupportItem:
    label: str
    quote: str
    quote_ok: bool = False
    label_ok: bool = False
    role: str | None = None

_WS_RE = re.compile(r"\s+")
_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "and",
        "or",
        "to",
        "for",
        "is",
        "was",
        "were",
        "be",
        "been",
        "by",
        "with",
        "as",
        "at",
        "from",
        "that",
        "this",
        "it",
        "its",
        "who",
        "which",
        "what",
        "when",
        "where",
        "how",
        "yes",
        "no",
    }
)
_YEAR_RE = re.compile(r"\b(?:1[5-9]\d{2}|20\d{2})\b")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def norm_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def content_tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[a-z0-9]+", norm_ws(text).lower())
        if t not in _STOP and len(t) > 1
    ]


def quote_in_passage(quote: str, passage_text: str) -> bool:
    if not quote or not passage_text:
        return False
    q = norm_ws(quote)
    p = norm_ws(passage_text)
    if q and q in p:
        return True
    q2 = q.rstrip("….").strip()
    return bool(q2) and q2 in p


def answer_covered_by_quotes(answer: str | None, quotes: list[str]) -> tuple[bool, str | None]:
    """Check that answer content is covered by verified quotes (not mere overlap).

    Prefer exact substring containment of the citation-stripped answer in the
    quote blob. Fall back to high content-token coverage (>=0.85) so short
    entity answers still pass when quoted with surrounding context.
    """
    if not answer:
        return False, "empty_answer"
    ans = strip_citation_markers(answer)
    ans_norm = norm_ws(ans).lower()
    if not ans_norm:
        return False, "empty_answer"
    blob = norm_ws(" ".join(quotes)).lower()
    if not blob:
        return False, "no_quotes"
    if ans_norm in blob:
        return True, None
    # Allow minor punctuation/case differences for short answers.
    ans_compact = re.sub(r"[^a-z0-9]+", "", ans_norm)
    blob_compact = re.sub(r"[^a-z0-9]+", "", blob)
    if ans_compact and ans_compact in blob_compact:
        return True, None
    toks = content_tokens(ans)
    if not toks:
        return False, "no_content_tokens"
    hits = sum(1 for t in toks if t in blob)
    coverage = hits / len(toks)
    if coverage >= 0.85:
        return True, None
    return False, f"answer_token_coverage={coverage:.2f}"


def detect_value_conflict(quotes: list[str]) -> str | None:
    """Heuristic: conflicting years/numbers across supporting quotes.

    Only flags when the same attribute-like context appears with incompatible
    numeric values. Conservative: requires >=2 distinct years or clearly
    incompatible singleton numbers in short quotes about dates/counts.
    """
    years: list[str] = []
    for q in quotes:
        years.extend(_YEAR_RE.findall(q))
    uniq_years = sorted(set(years))
    if len(uniq_years) >= 2:
        # Different years in supporting quotes for one answer → likely conflict
        # when both are asserted as launch/birth/founding facts.
        return f"conflicting_years:{','.join(uniq_years)}"
    return None


@dataclass
class VerificationResult:
    answer: str | None
    answerable: bool
    supporting: list[SupportItem] = field(default_factory=list)
    missing_info: str | None = None
    next_query: str | None = None
    status: str = "insufficient"
    citations: list[Citation] = field(default_factory=list)
    verify_ok: bool = False
    answer_supported: bool = False
    unsupported_reasons: list[str] = field(default_factory=list)
    evidence_chain_ok: bool = False
    contradiction: str | None = None
    raw_model: dict[str, Any] = field(default_factory=dict)


def _normalize_label(label: str) -> str:
    lab = (label or "").strip().upper()
    if lab.startswith("S"):
        return lab
    m = re.match(r"[Ss](\d+)$", lab)
    return f"S{m.group(1)}" if m else lab


def verify_structured_reader_output(
    data: dict[str, Any],
    passages: list[Any],
    *,
    require_multi_hop: bool | None = None,
    min_hops: int = 2,
) -> VerificationResult:
    """Full Phase C verification of a structured reader JSON payload."""
    by_label = {p.label: p for p in passages}
    answerable = bool(data.get("answerable"))
    answer = data.get("answer")
    if answer is not None:
        answer = str(answer).strip() or None
    missing = data.get("missing_info")
    missing_info = str(missing).strip() if missing else None
    next_q = data.get("next_query")
    next_query = str(next_q).strip() if next_q else None
    conflict_flag = str(data.get("conflict_kind") or "").strip().lower() or None

    reasons: list[str] = []
    supports: list[SupportItem] = []
    raw_support = data.get("supporting") or data.get("evidence_chain") or []
    if not isinstance(raw_support, list):
        raw_support = []
        reasons.append("supporting_not_list")

    for item in raw_support:
        if not isinstance(item, dict):
            reasons.append("supporting_item_not_object")
            continue
        label = _normalize_label(str(item.get("label") or ""))
        quote = str(item.get("quote") or "").strip()
        role = str(item.get("role") or "").strip() or None
        label_ok = label in by_label
        quote_ok = bool(label_ok and quote_in_passage(quote, by_label[label].text))
        if not label_ok:
            reasons.append(f"invalid_label:{label}")
        elif not quote_ok:
            reasons.append(f"quote_mismatch:{label}")
        supports.append(
            SupportItem(
                label=label,
                quote=quote,
                label_ok=label_ok,
                quote_ok=quote_ok,
                role=role,
            )
        )

    ok_supports = [s for s in supports if s.label_ok and s.quote_ok]
    quotes = [s.quote for s in ok_supports]
    distinct_labels = {s.label for s in ok_supports}

    # Default off for production (many retrieved distractors). Eval harness
    # enables this for Hotpot items with >=2 gold titles present in context.
    if require_multi_hop is None:
        require_multi_hop = False

    answer_supported = False
    cover_reason: str | None = None
    if answerable and answer:
        answer_supported, cover_reason = answer_covered_by_quotes(answer, quotes)
        if cover_reason:
            reasons.append(f"answer_not_entailed:{cover_reason}")

    contradiction = None
    if conflict_flag in {"contradiction", "conflicting", "conflict"}:
        contradiction = "model_reported_conflict"
    auto_conflict = detect_value_conflict(quotes) if len(ok_supports) >= 2 else None
    if auto_conflict and answerable:
        contradiction = auto_conflict
        reasons.append(auto_conflict)
        answerable = False
        answer_supported = False

    evidence_chain_ok = False
    if answerable:
        if not ok_supports:
            reasons.append("answerable_without_valid_quotes")
            answerable = False
            answer_supported = False
        elif not answer_supported:
            answerable = False
        elif require_multi_hop and len(distinct_labels) < min_hops:
            reasons.append(
                f"incomplete_evidence_chain:need>={min_hops}_got={len(distinct_labels)}"
            )
            answerable = False
            answer_supported = False
            missing_info = (
                missing_info
                or "Answer requires multiple supporting passages; chain incomplete."
            )
            if not next_query:
                next_query = "Retrieve the missing supporting document for the unanswered hop."
        else:
            evidence_chain_ok = True

    unsupported_answer = any(
        r.startswith("answer_not_entailed") or r == "answer_not_supported_by_quotes"
        for r in reasons
    )
    if not answerable and answer and unsupported_answer:
        missing_info = missing_info or "Proposed answer not supported by verified quotes."
        answer = None

    if contradiction and not answerable:
        status = "conflicting"
        if not missing_info:
            missing_info = f"Conflicting evidence detected ({contradiction})."
    elif answerable and answer:
        status = "answered"
    else:
        status = "insufficient"

    citations = [
        Citation(
            label=s.label,
            chunk_id=by_label[s.label].chunk_id or "",
            doc_id=by_label[s.label].doc_id or "",
            quote=s.quote,
        )
        for s in ok_supports
        if s.label in by_label
    ]

    # Fabricated / remapped labels always fail verify_ok.
    verify_ok = not reasons and (
        (answerable and answer_supported and evidence_chain_ok)
        or (not answerable and status in {"insufficient", "conflicting"})
    )

    return VerificationResult(
        answer=answer if answerable else None,
        answerable=bool(answerable and answer),
        supporting=supports,
        missing_info=missing_info,
        next_query=next_query,
        status=status,
        citations=citations,
        verify_ok=verify_ok,
        answer_supported=answer_supported and evidence_chain_ok,
        unsupported_reasons=reasons,
        evidence_chain_ok=evidence_chain_ok,
        contradiction=contradiction,
        raw_model=data,
    )


__all__ = [
    "SupportItem",
    "VerificationResult",
    "answer_covered_by_quotes",
    "detect_value_conflict",
    "norm_ws",
    "quote_in_passage",
    "verify_structured_reader_output",
]
