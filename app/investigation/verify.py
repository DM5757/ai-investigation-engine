"""Answer-to-evidence verification with STRICT / SOFT multi-hop policies (Phase C.1).

Deterministic checks for labels, exact quotes, answer coverage, and evidence-chain
completeness. Quote existence alone does not entail support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from app.investigation.citations import strip_citation_markers
from app.schemas.evidence import Citation

PolicyName = Literal["strict", "soft"]


class MultiHopPolicy(StrEnum):
    """How incomplete evidence chains affect final status."""

    STRICT = "strict"  # incomplete chain → insufficient
    SOFT = "soft"  # incomplete chain + quote-supported answer → partial


# Default calibrated coverage threshold (Phase B was 0.60; Phase C hard was 0.85).
# 0.65 recovers observed ~0.67 borderline false rejections while staying above 0.60.
DEFAULT_COVERAGE_THRESHOLD = 0.65


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


def answer_covered_by_quotes(
    answer: str | None,
    quotes: list[str],
    *,
    coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
) -> tuple[bool, str | None, float]:
    """Check answer content is covered by verified quotes.

    Returns (ok, reason_if_not, coverage). Coverage is 1.0 for substring hits.
    """
    if not answer:
        return False, "empty_answer", 0.0
    ans = strip_citation_markers(answer)
    ans_norm = norm_ws(ans).lower()
    if not ans_norm:
        return False, "empty_answer", 0.0
    blob = norm_ws(" ".join(quotes)).lower()
    if not blob:
        return False, "no_quotes", 0.0
    if ans_norm in blob:
        return True, None, 1.0
    ans_compact = re.sub(r"[^a-z0-9]+", "", ans_norm)
    blob_compact = re.sub(r"[^a-z0-9]+", "", blob)
    if ans_compact and ans_compact in blob_compact:
        return True, None, 1.0
    toks = content_tokens(ans)
    if not toks:
        return False, "no_content_tokens", 0.0
    hits = sum(1 for t in toks if t in blob)
    coverage = hits / len(toks)
    if coverage >= coverage_threshold:
        return True, None, coverage
    return False, f"answer_token_coverage={coverage:.2f}", coverage


def detect_value_conflict(quotes: list[str]) -> str | None:
    """Conservative conflicting-years signal across supporting quotes."""
    years: list[str] = []
    for q in quotes:
        years.extend(_YEAR_RE.findall(q))
    uniq_years = sorted(set(years))
    if len(uniq_years) >= 2:
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
    policy: str = MultiHopPolicy.STRICT.value
    coverage: float = 0.0
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
    policy: MultiHopPolicy | PolicyName = MultiHopPolicy.STRICT,
    coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
) -> VerificationResult:
    """Verify structured reader JSON under STRICT or SOFT multi-hop policy."""
    if isinstance(policy, str):
        policy = MultiHopPolicy(policy.lower())

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

    if require_multi_hop is None:
        require_multi_hop = False

    coverage = 0.0
    answer_supported = False
    if answerable and answer:
        answer_supported, cover_reason, coverage = answer_covered_by_quotes(
            answer, quotes, coverage_threshold=coverage_threshold
        )
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
    status = "insufficient"
    final_answer = answer

    if contradiction and not answerable:
        status = "conflicting"
        final_answer = None
        if not missing_info:
            missing_info = f"Conflicting evidence detected ({contradiction})."
    elif answerable:
        if not ok_supports:
            reasons.append("answerable_without_valid_quotes")
            answerable = False
            answer_supported = False
            final_answer = None
            status = "insufficient"
            missing_info = missing_info or "No valid supporting quotes."
        elif not answer_supported:
            # Unsupported full answer — never emit as answered/partial final.
            answerable = False
            final_answer = None
            status = "insufficient"
            missing_info = (
                missing_info or "Proposed answer not supported by verified quotes."
            )
        elif require_multi_hop and len(distinct_labels) < min_hops:
            reasons.append(
                f"incomplete_evidence_chain:need>={min_hops}_got={len(distinct_labels)}"
            )
            missing_info = (
                missing_info
                or "Answer requires multiple supporting passages; chain incomplete."
            )
            if not next_query:
                next_query = (
                    "Retrieve the missing supporting document for the unanswered hop."
                )
            if policy is MultiHopPolicy.SOFT:
                # Retain only quote-supported answer as partial — not a verified
                # full multi-hop conclusion (evidence_chain_ok stays False).
                status = "partial"
                answerable = False
                final_answer = answer
                answer_supported = True  # partial content is quote-supported
            else:
                status = "insufficient"
                answerable = False
                answer_supported = False
                final_answer = None
        else:
            evidence_chain_ok = True
            status = "answered"
            final_answer = answer
    else:
        status = "insufficient"
        final_answer = None

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

    # STRICT full answer or SOFT partial with supported content can be verify_ok
    # when labels/quotes are valid; incomplete-chain reason is expected under SOFT.
    blocking = [
        r
        for r in reasons
        if not (
            policy is MultiHopPolicy.SOFT
            and status == "partial"
            and r.startswith("incomplete_evidence_chain")
        )
    ]
    verify_ok = not blocking and (
        (status == "answered" and evidence_chain_ok and bool(final_answer))
        or (status == "partial" and answer_supported and bool(final_answer))
        or (status in {"insufficient", "conflicting"} and final_answer is None)
    )

    return VerificationResult(
        answer=final_answer,
        answerable=bool(status == "answered" and final_answer),
        supporting=supports,
        missing_info=missing_info,
        next_query=next_query,
        status=status,
        citations=citations,
        verify_ok=verify_ok,
        answer_supported=bool(answer_supported and (evidence_chain_ok or status == "partial")),
        unsupported_reasons=reasons,
        evidence_chain_ok=evidence_chain_ok,
        contradiction=contradiction,
        policy=policy.value,
        coverage=coverage,
        raw_model=data,
    )


__all__ = [
    "DEFAULT_COVERAGE_THRESHOLD",
    "MultiHopPolicy",
    "SupportItem",
    "VerificationResult",
    "answer_covered_by_quotes",
    "detect_value_conflict",
    "norm_ws",
    "quote_in_passage",
    "verify_structured_reader_output",
]
