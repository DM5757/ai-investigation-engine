"""Synthesize answers only from verified, labeled claims."""

from __future__ import annotations

import re

from app.errors import BudgetExceeded, LLMOutputInvalid, LLMUnavailable
from app.investigation.aggregator import assign_source_labels
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
    """Keep only citations whose labels appear in the answer text.

    If the answer has no [Sn] markers, keep a single highest-priority citation
    when exactly one unique doc is present; otherwise keep citations unchanged
    only when the answer is empty (caller handles degraded paths).
    """
    if not answer or not citations:
        return []
    used = citation_labels_in_text(answer)
    if used:
        pruned = [c for c in citations if c.label in used]
        return pruned or citations[:1]
    docs = {c.doc_id for c in citations}
    if len(docs) == 1:
        return citations[:1]
    # Prefer not to ship an uncapped citation dump without in-text labels
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
    citations = claims_to_citations(labeled)
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
        return text, prune_citations_to_answer(text, citations)
    if not labeled:
        return abstention_reason or "No verified claims.", []

    comparison = _deterministic_comparison(question, labeled)
    if comparison is not None:
        text, selected = comparison
        citations = claims_to_citations(selected)
        return text, prune_citations_to_answer(text, citations)

    multihop = _deterministic_multihop(question, labeled)
    if multihop is not None:
        text, selected = multihop
        citations = claims_to_citations(selected)
        return text, prune_citations_to_answer(text, citations)

    # Concise factual: prefer the highest-priority claim's quote as the answer.
    primary = labeled[0]
    quote = (primary.quote or primary.value or "").strip()
    if quote:
        text = f"{quote} [{primary.source_label}]."
        return text, prune_citations_to_answer(text, claims_to_citations([primary]))

    by_doc: dict[str, Claim] = {}
    for claim in labeled:
        by_doc.setdefault(claim.doc_id, claim)
    selected = list(by_doc.values())[:3]
    selected = assign_source_labels(selected)
    citations = claims_to_citations(selected)
    sentences = [
        f"{c.subject} {c.attribute}: {c.value} [{c.source_label}]." for c in selected
    ]
    text = " ".join(sentences)
    return text, prune_citations_to_answer(text, citations)


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
    lines = [
        f"{entities[i]}: {picked[i].quote} [{picked[i].source_label}]"
        for i in range(len(picked))
    ]
    if direction in {"west", "east"}:
        ranks = [state_westness(f"{c.quote} {c.value}") for c in picked]
        r0, r1 = ranks[0], ranks[1]
        if r0 is not None and r1 is not None:
            winner_i = (0 if r0 < r1 else 1) if direction == "west" else (0 if r0 > r1 else 1)
            lines.append(
                f"Therefore {entities[winner_i]} is further {direction} "
                f"[{picked[0].source_label}, {picked[1].source_label}]."
            )
    return " ".join(lines), picked


def _deterministic_multihop(
    question: str, labeled: list[Claim]
) -> tuple[str, list[Claim]] | None:
    """Bridge multi-hop: cite first-hop context plus the answer-bearing claim."""
    entities = extract_focus_entities(question)
    if not should_attempt_bridge(question, entities):
        return None
    if len({c.doc_id for c in labeled}) < 2:
        return None
    q_low = question.lower()
    asks_date = bool(re.search(r"\b(?:what date|premiered)\b", q_low))
    asks_country = bool(re.search(r"\b(?:which country|king of|queen of)\b", q_low))

    answer_claim: Claim | None = None
    for claim in labeled:
        hay = f"{claim.value} {claim.quote}"
        if asks_date and re.search(r"\b(?:premiered|premiere)\b", hay, re.I):
            answer_claim = claim
            break
        if asks_country and re.search(r"\b(?:king of|queen of)\b", hay, re.I):
            answer_claim = claim
            break
    if answer_claim is None:
        return None

    bridge_claim: Claim | None = None
    if entities:
        bridge_claim = best_claim_for_entity(labeled, entities[0])
    if bridge_claim is None or bridge_claim.doc_id == answer_claim.doc_id:
        for claim in labeled:
            if claim.doc_id != answer_claim.doc_id:
                bridge_claim = claim
                break
    if bridge_claim is None or bridge_claim.doc_id == answer_claim.doc_id:
        return None

    selected = assign_source_labels([bridge_claim, answer_claim])
    text = (
        f"{selected[0].quote} [{selected[0].source_label}] "
        f"{selected[1].quote} [{selected[1].source_label}]"
    )
    return text, selected


def llm_synthesize(
    *,
    question: str,
    claims: list[Claim],
    conflicts: list[Conflict],
    status: AnswerStatus,
    llm: LLMClient,
) -> tuple[str, list[Citation], UsageStats]:
    """Ask LLM to phrase an answer strictly from labeled claims."""
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
    user = (
        f"Question: {question}\nStatus: {status}\nClaims:\n{claim_lines}\n"
        f"Conflicts:\n{conflict_lines or '(none)'}\n"
        "Write a concise answer with only the [Sn] citations that support it. "
        "Do not cite unrelated sources. When Status is answered or partial and "
        "claims cover each compared entity, give the comparative conclusion; "
        "do not refuse as insufficient."
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
) -> tuple[str | None, list[Citation], UsageStats, bool]:
    """Prefer LLM phrasing unless deterministic evidence path is requested.

    Returns ``(text, cites, usage, used_llm)``.
    """
    if status in ("insufficient", "llm_unavailable") or llm is None or prefer_deterministic:
        text, cites = deterministic_synthesize(
            question=question,
            status=status,
            claims=claims,
            conflicts=conflicts,
            abstention_reason=abstention_reason,
        )
        return text, cites, UsageStats(), False
    # Conflicts: structured deterministic list is clearer and saves a provider call.
    if status == "conflicting":
        text, cites = deterministic_synthesize(
            question=question,
            status=status,
            claims=claims,
            conflicts=conflicts,
            abstention_reason=abstention_reason,
        )
        return text, cites, UsageStats(), False
    try:
        text, cites, usage = llm_synthesize(
            question=question,
            claims=claims,
            conflicts=conflicts,
            status=status,
            llm=llm,
        )
        if status in ("answered", "partial") and _llm_hedged_insufficient(text):
            # Status already established evidence; do not ship an LLM refusal.
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
    r"claims\s+are\s+insufficient"
    r")\b",
    re.IGNORECASE,
)


def _llm_hedged_insufficient(text: str | None) -> bool:
    return bool(text and _HEDGE_INSUFFICIENT.search(text))


def citation_labels_in_text(text: str) -> set[str]:
    return set(_CITE_RE.findall(text))
