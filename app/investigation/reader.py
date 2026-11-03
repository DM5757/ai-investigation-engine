"""Experimental quote-verified passage-level LLM reader (Phase B/C).

Not the production default. Enabled only via Settings.experimental_passage_reader
or explicit callers (E0 / Phase C harness). Legacy extraction/synthesis remains.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.errors import BudgetExceeded, LLMOutputInvalid, LLMUnavailable
from app.investigation.citations import extract_citation_labels
from app.investigation.injection import scan_injection
from app.investigation.verify import (
    DEFAULT_COVERAGE_THRESHOLD,
    MultiHopPolicy,
    PolicyName,
    verify_structured_reader_output,
)
from app.llm.prompts.reader import READER_BASELINE_SYSTEM, READER_SYSTEM
from app.llm.types import ChatMessage, ChatResult, LLMClient
from app.schemas.evidence import Citation, UsageStats


@dataclass
class ReaderPassage:
    """One numbered evidence passage supplied to the reader."""

    label: str
    title: str
    text: str
    doc_id: str | None = None
    chunk_id: str | None = None


@dataclass
class ReaderSupport:
    label: str
    quote: str
    quote_ok: bool = False
    label_ok: bool = False
    role: str | None = None  # hop1|hop2|bridge|support


@dataclass
class ReaderOutput:
    """Verified reader result ready for evaluation / AnswerResponse mapping."""

    answer: str | None
    answerable: bool
    supporting: list[ReaderSupport] = field(default_factory=list)
    missing_info: str | None = None
    next_query: str | None = None
    status: str = "insufficient"
    citations: list[Citation] = field(default_factory=list)
    usage: UsageStats = field(default_factory=UsageStats)
    verify_ok: bool = False
    answer_supported: bool = False
    unsupported_reasons: list[str] = field(default_factory=list)
    evidence_chain_ok: bool = False
    contradiction: str | None = None
    policy: str = MultiHopPolicy.STRICT.value
    coverage: float = 0.0
    raw_model: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    mode: str = "structured_reader"


def format_passages_for_prompt(
    passages: list[ReaderPassage],
    *,
    max_chars: int = 12_000,
) -> tuple[str, list[ReaderPassage]]:
    """Build numbered prompt block; truncate to token/char budget preserving order."""
    used: list[ReaderPassage] = []
    parts: list[str] = []
    total = 0
    for p in passages:
        scan = scan_injection(p.text)
        body = scan.wrapped_text if scan.flagged else p.text
        block = f"[{p.label}] title={p.title}\n{body}\n"
        if total + len(block) > max_chars and used:
            break
        parts.append(block)
        used.append(p)
        total += len(block)
    return "\n".join(parts), used


def _parse_reader_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise LLMOutputInvalid("empty reader output")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise LLMOutputInvalid("reader output is not JSON") from None
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise LLMOutputInvalid("reader JSON must be an object")
    return data


def verify_reader_payload(
    data: dict[str, Any],
    passages: list[ReaderPassage],
    *,
    require_multi_hop: bool | None = None,
    min_hops: int = 2,
    policy: MultiHopPolicy | PolicyName = MultiHopPolicy.STRICT,
    coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
) -> ReaderOutput:
    """Deterministically verify labels, quotes, entailment, and evidence chain."""
    result = verify_structured_reader_output(
        data,
        passages,
        require_multi_hop=require_multi_hop,
        min_hops=min_hops,
        policy=policy,
        coverage_threshold=coverage_threshold,
    )
    supports = [
        ReaderSupport(
            label=s.label,
            quote=s.quote,
            quote_ok=s.quote_ok,
            label_ok=s.label_ok,
            role=s.role,
        )
        for s in result.supporting
    ]
    return ReaderOutput(
        answer=result.answer,
        answerable=result.answerable,
        supporting=supports,
        missing_info=result.missing_info,
        next_query=result.next_query,
        status=result.status,
        citations=result.citations,
        verify_ok=result.verify_ok,
        answer_supported=result.answer_supported,
        unsupported_reasons=result.unsupported_reasons,
        evidence_chain_ok=result.evidence_chain_ok,
        contradiction=result.contradiction,
        policy=result.policy,
        coverage=result.coverage,
        raw_model=result.raw_model,
    )


def read_passages(
    *,
    question: str,
    passages: list[ReaderPassage],
    llm: LLMClient,
    max_passages: int = 10,
    max_chars: int = 12_000,
    temperature: float = 0.0,
    require_multi_hop: bool | None = None,
    min_hops: int = 2,
    policy: MultiHopPolicy | PolicyName = MultiHopPolicy.STRICT,
    coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
) -> ReaderOutput:
    """One structured LLM reader call + deterministic verification."""
    capped = passages[:max_passages]
    prompt_block, used = format_passages_for_prompt(capped, max_chars=max_chars)
    if not used:
        return ReaderOutput(
            answer=None,
            answerable=False,
            missing_info="No passages provided.",
            status="insufficient",
            unsupported_reasons=["no_passages"],
        )
    user = (
        f"Question: {question}\n\nPassages:\n{prompt_block}\n"
        "Respond with the JSON object only."
    )
    try:
        result: ChatResult = llm.chat(
            [
                ChatMessage(role="system", content=READER_SYSTEM),
                ChatMessage(role="user", content=user),
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            stage="passage_reader",
        )
    except BudgetExceeded:
        raise
    except LLMUnavailable:
        raise

    data = _parse_reader_json(result.content or "")
    out = verify_reader_payload(
        data,
        used,
        require_multi_hop=require_multi_hop,
        min_hops=min_hops,
        policy=policy,
        coverage_threshold=coverage_threshold,
    )
    out.usage = result.usage
    out.provider = result.provider
    out.model = result.model
    out.mode = "structured_reader_v2"
    out.raw_model = data
    return out


def read_passages_baseline(
    *,
    question: str,
    passages: list[ReaderPassage],
    llm: LLMClient,
    max_passages: int = 10,
    max_chars: int = 12_000,
    temperature: float = 0.0,
) -> ReaderOutput:
    """Simple LLM-over-passages baseline (no structured schema / weak verify)."""
    capped = passages[:max_passages]
    prompt_block, used = format_passages_for_prompt(capped, max_chars=max_chars)
    if not used:
        return ReaderOutput(
            answer=None,
            answerable=False,
            missing_info="No passages provided.",
            status="insufficient",
            mode="llm_baseline",
            unsupported_reasons=["no_passages"],
        )
    user = f"Question: {question}\n\nPassages:\n{prompt_block}\n"
    result = llm.chat(
        [
            ChatMessage(role="system", content=READER_BASELINE_SYSTEM),
            ChatMessage(role="user", content=user),
        ],
        temperature=temperature,
        stage="passage_reader_baseline",
    )
    text = (result.content or "").strip()
    labels = extract_citation_labels(text)
    by_label = {p.label: p for p in used}
    citations: list[Citation] = []
    for lab in sorted(labels):
        p = by_label.get(lab)
        if not p:
            continue
        citations.append(
            Citation(label=lab, chunk_id=p.chunk_id or "", doc_id=p.doc_id or "", quote="")
        )
    answerable = bool(text) and "insufficient" not in text.lower()
    return ReaderOutput(
        answer=text or None,
        answerable=answerable,
        supporting=[
            ReaderSupport(label=c.label, quote="", label_ok=True, quote_ok=False)
            for c in citations
        ],
        status="answered" if answerable else "insufficient",
        citations=citations,
        usage=result.usage,
        verify_ok=False,
        answer_supported=False,
        unsupported_reasons=["baseline_unverified"],
        provider=result.provider,
        model=result.model,
        mode="llm_baseline",
        raw_model={"text": text},
    )


def passages_from_retrieval_hits(hits: list[Any], *, max_n: int = 10) -> list[ReaderPassage]:
    """Convert hybrid retrieval hits to reader passages."""
    out: list[ReaderPassage] = []
    for i, hit in enumerate(hits[:max_n], start=1):
        chunk = getattr(hit, "chunk", None)
        if chunk is None:
            continue
        out.append(
            ReaderPassage(
                label=f"S{i}",
                title=str(getattr(chunk, "title", None) or "(untitled)"),
                text=str(getattr(chunk, "text", "") or ""),
                doc_id=str(getattr(chunk, "doc_id", "") or "") or None,
                chunk_id=str(getattr(chunk, "chunk_id", "") or "") or None,
            )
        )
    return out


def passages_from_gold_paragraphs(
    paragraphs: list[dict[str, Any]],
) -> list[ReaderPassage]:
    """Oracle evidence from Hotpot gold paragraphs."""
    out: list[ReaderPassage] = []
    for i, para in enumerate(paragraphs, start=1):
        out.append(
            ReaderPassage(
                label=f"S{i}",
                title=str(para.get("title") or f"gold_{i}"),
                text=str(para.get("text") or ""),
                doc_id=None,
                chunk_id=None,
            )
        )
    return out


__all__ = [
    "ReaderOutput",
    "ReaderPassage",
    "ReaderSupport",
    "format_passages_for_prompt",
    "passages_from_gold_paragraphs",
    "passages_from_retrieval_hits",
    "read_passages",
    "read_passages_baseline",
    "verify_reader_payload",
]
