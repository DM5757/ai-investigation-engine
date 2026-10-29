"""Synthesize answers only from verified, labeled claims."""

from __future__ import annotations

import re

from app.errors import LLMOutputInvalid, LLMUnavailable
from app.investigation.aggregator import assign_source_labels
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


def deterministic_synthesize(
    *,
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
        return "\n".join(parts), citations
    if not labeled:
        return abstention_reason or "No verified claims.", []
    sentences = [
        f"{c.subject} {c.attribute}: {c.value} [{c.source_label}]." for c in labeled
    ]
    return " ".join(sentences), citations


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
        f"[{c.source_label}] subject={c.subject} attr={c.attribute} "
        f"value={c.value} quote={c.quote!r} doc={c.doc_id}"
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
        "Write the answer with [Sn] citations."
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
    return text, citations, result.usage


def synthesize_answer(
    *,
    question: str,
    status: AnswerStatus,
    claims: list[Claim],
    conflicts: list[Conflict],
    abstention_reason: str | None,
    llm: LLMClient | None,
) -> tuple[str | None, list[Citation], UsageStats, bool]:
    """Prefer LLM phrasing; fall back to deterministic synthesis."""
    if status in ("insufficient",) or llm is None:
        text, cites = deterministic_synthesize(
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
        return text, cites, usage, True
    except (LLMUnavailable, LLMOutputInvalid, Exception):
        text, cites = deterministic_synthesize(
            status=status,
            claims=claims,
            conflicts=conflicts,
            abstention_reason=abstention_reason,
        )
        return text, cites, UsageStats(), False


def citation_labels_in_text(text: str) -> set[str]:
    return set(_CITE_RE.findall(text))
