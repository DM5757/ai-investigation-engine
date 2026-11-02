"""Synthesize answers only from verified, labeled claims."""

from __future__ import annotations

import re

from app.errors import BudgetExceeded, LLMOutputInvalid, LLMUnavailable
from app.investigation.aggregator import assign_source_labels
from app.investigation.answer_span import (
    extract_span_from_claims,
    needs_llm_synthesis,
)
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
from app.llm.prompts.synthesizer import SYNTHESIZER_SYSTEM
from app.llm.types import ChatMessage, LLMClient
from app.schemas.evidence import AnswerStatus, Citation, Claim, Conflict, UsageStats

_CITE_RE = re.compile(r"\[(S\d+)\]")


def claims_to_citations(claims: list[Claim]) -> list[Citation]:
    labeled = assign_source_labels(claims)
    return [
        Citation(
            label=c.source_label or f"S{i}",
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            quote=c.quote,
        )
        for i, c in enumerate(labeled, start=1)
    ]


def prune_citations_to_answer(
    answer: str | None,
    citations: list[Citation],
) -> list[Citation]:
    """Keep only citations whose labels appear in the answer text."""
    if not answer or not citations:
        return []
    used = citation_labels_in_text(answer)
    if used:
        pruned = [c for c in citations if c.label in used]
        return pruned or citations[:1]
    docs = {c.doc_id for c in citations}
    if len(docs) == 1:
        return citations[:1]
    return citations[:3]


def deterministic_synthesize(
    *,
    question: str,
    status: AnswerStatus,
    claims: list[Claim],
    conflicts: list[Conflict],
    abstention_reason: str | None,
) -> tuple[str | None, list[Citation]]:
    """Build a grounded answer without calling an LLM."""
    labeled = assign_source_labels([c for c in claims if c.verified])
    if status == "insufficient":
        return abstention_reason or "Insufficient evidence to answer.", []
    if status == "llm_unavailable":
        return None, []
    if status == "conflicting":
        parts: list[str] = ["Sources conflict:"]
        for conf in conflicts:
            for side in conf.sides:
                label = next(
                    (c.source_label for c in labeled if c.claim_id == side.claim_id),
                    side.doc_id,
                )
                parts.append(
                    f"- {conf.subject}/{conf.attribute}: {side.value} [{label}]"
                )
        text = "\n".join(parts)
        return text, prune_citations_to_answer(text, claims_to_citations(labeled))
    if not labeled:
        return abstention_reason or "No verified claims.", []

    span_hit = extract_span_from_claims(question, labeled)
    if span_hit is not None:
        span, support, _conf = span_hit
        support = assign_source_labels(support)
        labels = ", ".join(c.source_label or "?" for c in support)
        text = f"{span} [{labels}]."
        return text, prune_citations_to_answer(text, claims_to_citations(support))

    comparison = _deterministic_comparison(question, labeled)
    if comparison is not None:
        text, selected = comparison
        return text, prune_citations_to_answer(text, claims_to_citations(selected))

    multihop = _deterministic_multihop(question, labeled)
    if multihop is not None:
        text, selected = multihop
        return text, prune_citations_to_answer(text, claims_to_citations(selected))

    # Last resort: one short claim value (not a full dump of every doc).
    primary = labeled[0]
    value = (primary.value or primary.quote or "").strip()
    if len(value) > 160:
        value = value[:157].rstrip() + "..."
    text = f"{value} [{primary.source_label}]."
    return text, prune_citations_to_answer(text, claims_to_citations([primary]))


def _deterministic_comparison(
    question: str, labeled: list[Claim]
) -> tuple[str, list[Claim]] | None:
    if not is_comparison_question(question):
        return None
    entities = extract_focus_entities(question)
    if len(entities) < 2:
        return None
    picked: list[Claim] = []
    for ent in entities[:2]:
        claim = best_claim_for_entity(labeled, ent)
        if claim is None:
            return None
        picked.append(claim)
    picked = assign_source_labels(picked)
    direction = comparison_direction(question)
    if direction in {"west", "east"}:
        ranks = [state_westness(f"{c.quote} {c.value}") for c in picked]
        r0, r1 = ranks[0], ranks[1]
        if r0 is not None and r1 is not None:
            winner_i = (0 if r0 < r1 else 1) if direction == "west" else (0 if r0 > r1 else 1)
            labels = f"{picked[0].source_label}, {picked[1].source_label}"
            text = f"{entities[winner_i]} [{labels}]."
            return text, picked
    lines = [
        f"{entities[i]}: {picked[i].quote} [{picked[i].source_label}]"
        for i in range(len(picked))
    ]
    return " ".join(lines), picked


def _deterministic_multihop(
    question: str, labeled: list[Claim]
) -> tuple[str, list[Claim]] | None:
    """Bridge multi-hop: prefer a short answer span with multi-doc citations."""
    entities = extract_focus_entities(question)
    if not should_attempt_bridge(question, entities):
        return None
    span_hit = extract_span_from_claims(question, labeled)
    if span_hit is None:
        return None
    span, support, conf = span_hit
    if conf < 0.55:
        return None
    support = assign_source_labels(support)
    labels = ", ".join(c.source_label or "?" for c in support)
    return f"{span} [{labels}].", support


def llm_synthesize(
    *,
    question: str,
    claims: list[Claim],
    conflicts: list[Conflict],
    status: AnswerStatus,
    llm: LLMClient,
    hint_span: str | None = None,
) -> tuple[str, list[Citation], UsageStats]:
    """Ask LLM to phrase a short answer strictly from labeled claims."""
    labeled = assign_source_labels([c for c in claims if c.verified])
    citations = claims_to_citations(labeled)
    claim_lines = "\n".join(
        f"[{c.source_label}] title={c.source_title or c.doc_id!r} "
        f"subject={c.subject} attr={c.attribute} "
        f"value={c.value} quote={c.quote!r}"
        for c in labeled
    )
    conflict_lines = "\n".join(
        f"CONFLICT {c.subject}/{c.attribute}: "
        + "; ".join(f"{s.doc_id}={s.value}" for s in c.sides)
        for c in conflicts
    )
    hint = (
        f"\nCandidate short span (verify before using): {hint_span!r}\n"
        if hint_span
        else ""
    )
    user = (
        f"Question: {question}\nStatus: {status}\nClaims:\n{claim_lines}\n"
        f"Conflicts:\n{conflict_lines or '(none)'}\n{hint}"
        "Write a SHORT answer (ideally a few words or one short sentence) with "
        "inline [Sn] citations only for claims you used. Prefer the exact entity, "
        "date, place, or name the question asks for. Do not dump full paragraphs."
    )
    result = llm.chat(
        [
            ChatMessage(role="system", content=SYNTHESIZER_SYSTEM),
            ChatMessage(role="user", content=user),
        ],
        stage="synthesize",
    )
    text = (result.content or "").strip()
    if not text:
        raise LLMOutputInvalid("empty synthesizer output")
    return text, prune_citations_to_answer(text, citations), result.usage


def synthesize_answer(
    *,
    question: str,
    status: AnswerStatus,
    claims: list[Claim],
    conflicts: list[Conflict],
    abstention_reason: str | None,
    llm: LLMClient | None,
    prefer_deterministic: bool = False,
    adaptive: bool = True,
) -> tuple[str | None, list[Citation], UsageStats, bool]:
    """Adaptive synthesis: short deterministic spans when confident, else LLM.

    Returns ``(text, cites, usage, used_llm)``.
    """
    span_hit = (
        extract_span_from_claims(question, claims)
        if status not in {"insufficient", "llm_unavailable"}
        else None
    )
    span_conf = span_hit[2] if span_hit else None
    hint = span_hit[0] if span_hit else None

    force_det = (
        prefer_deterministic
        or llm is None
        or status in {"insufficient", "llm_unavailable", "conflicting"}
        or (adaptive and not needs_llm_synthesis(
            question, claims, status=status, span_confidence=span_conf
        ))
    )
    if force_det:
        text, cites = deterministic_synthesize(
            question=question,
            status=status,
            claims=claims,
            conflicts=conflicts,
            abstention_reason=abstention_reason,
        )
        return text, cites, UsageStats(), False

    assert llm is not None  # for type checkers; force_det handles None above
    try:
        text, cites, usage = llm_synthesize(
            question=question,
            claims=claims,
            conflicts=conflicts,
            status=status,
            llm=llm,
            hint_span=hint,
        )
        if status in ("answered", "partial") and _llm_hedged_insufficient(text):
            text2, cites2 = deterministic_synthesize(
                question=question,
                status=status,
                claims=claims,
                conflicts=conflicts,
                abstention_reason=abstention_reason,
            )
            return text2, cites2, usage, True
        return text, cites, usage, True
    except BudgetExceeded:
        raise
    except (LLMUnavailable, LLMOutputInvalid, Exception):
        text, cites = deterministic_synthesize(
            question=question,
            status=status,
            claims=claims,
            conflicts=conflicts,
            abstention_reason=abstention_reason,
        )
        return text, cites, UsageStats(), False


_HEDGE_INSUFFICIENT = re.compile(
    r"\b("
    r"insufficient(?:\s+information|\s+evidence|\s+to)?|"
    r"cannot\s+determine|do\s+not\s+provide|"
    r"not\s+(?:enough|sufficient)\s+(?:information|evidence)|"
    r"claims\s+are\s+insufficient|"
    r"not\s+(?:mentioned|present|stated|recorded|found)|"
    r"no\s+(?:information|evidence|mention|data)\s+(?:about|on|for|regarding)"
    r")\b",
    re.IGNORECASE,
)


def _llm_hedged_insufficient(text: str | None) -> bool:
    return bool(text and _HEDGE_INSUFFICIENT.search(text))


def citation_labels_in_text(text: str) -> set[str]:
    return set(_CITE_RE.findall(text))
