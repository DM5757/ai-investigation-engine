"""Experimental quote-verified passage-level LLM reader (Phase B).

Not the production default. Enabled only via Settings.experimental_passage_reader
or explicit callers (E0 harness). Legacy extraction/synthesis remains untouched.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.errors import BudgetExceeded, LLMOutputInvalid, LLMUnavailable
from app.investigation.citations import extract_citation_labels, strip_citation_markers
from app.investigation.injection import scan_injection
from app.llm.prompts.reader import READER_BASELINE_SYSTEM, READER_SYSTEM
from app.llm.types import ChatMessage, ChatResult, LLMClient
from app.schemas.evidence import Citation, UsageStats

_WS_RE = re.compile(r"\s+")


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
    raw_model: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    mode: str = "structured_reader"


def _norm_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _quote_in_passage(quote: str, passage_text: str) -> bool:
    if not quote or not passage_text:
        return False
    q = _norm_ws(quote)
    p = _norm_ws(passage_text)
    if q and q in p:
        return True
    # Allow minor quote truncation markers
    q2 = q.rstrip("….").strip()
    return bool(q2) and q2 in p


def _answer_supported_by_quotes(answer: str | None, quotes: list[str]) -> bool:
    """Require substantial overlap between answer tokens and supporting quotes."""
    if not answer:
        return False
    ans = strip_citation_markers(answer)
    ans_norm = _norm_ws(ans).lower()
    if not ans_norm:
        return False
    blob = _norm_ws(" ".join(quotes)).lower()
    if not blob:
        return False
    if ans_norm in blob:
        return True
    # Token overlap (stopword-light)
    stop = {"the", "a", "an", "of", "in", "on", "and", "or", "to", "for", "is", "was"}
    toks = [t for t in re.findall(r"[a-z0-9]+", ans_norm) if t not in stop]
    if not toks:
        return False
    hits = sum(1 for t in toks if t in blob)
    return (hits / len(toks)) >= 0.6


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
        # Extract first JSON object if model wrapped it
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
) -> ReaderOutput:
    """Deterministically verify labels, exact quotes, and answer support."""
    by_label = {p.label: p for p in passages}
    answerable = bool(data.get("answerable"))
    answer = data.get("answer")
    if answer is not None:
        answer = str(answer).strip() or None
    missing = data.get("missing_info")
    missing_info = str(missing).strip() if missing else None
    next_q = data.get("next_query")
    next_query = str(next_q).strip() if next_q else None

    reasons: list[str] = []
    supports: list[ReaderSupport] = []
    raw_support = data.get("supporting") or []
    if not isinstance(raw_support, list):
        raw_support = []
        reasons.append("supporting_not_list")

    for item in raw_support:
        if not isinstance(item, dict):
            reasons.append("supporting_item_not_object")
            continue
        label = str(item.get("label") or "").strip().upper()
        if not label.startswith("S"):
            # Normalize s1 -> S1
            m = re.match(r"[Ss](\d+)$", label)
            label = f"S{m.group(1)}" if m else label
        quote = str(item.get("quote") or "").strip()
        label_ok = label in by_label
        quote_ok = bool(label_ok and _quote_in_passage(quote, by_label[label].text))
        if not label_ok:
            reasons.append(f"invalid_label:{label}")
        elif not quote_ok:
            reasons.append(f"quote_mismatch:{label}")
        supports.append(
            ReaderSupport(label=label, quote=quote, label_ok=label_ok, quote_ok=quote_ok)
        )

    ok_supports = [s for s in supports if s.label_ok and s.quote_ok]
    quotes = [s.quote for s in ok_supports]
    answer_supported = _answer_supported_by_quotes(answer, quotes) if answerable else False

    if answerable and not ok_supports:
        reasons.append("answerable_without_valid_quotes")
        answerable = False
    if answerable and answer and not answer_supported:
        reasons.append("answer_not_supported_by_quotes")
        answerable = False
        answer_supported = False
    if (
        not answerable
        and answer
        and "answer_not_supported_by_quotes" in reasons
    ):
        missing_info = missing_info or "Proposed answer not supported by verified quotes."
        answer = None

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

    if answerable and answer:
        status = "answered"
    elif ok_supports and answer:
        status = "partial"
    else:
        status = "insufficient"

    verify_ok = not reasons and (
        (answerable and answer_supported and bool(ok_supports))
        or (not answerable)
    )
    return ReaderOutput(
        answer=answer,
        answerable=answerable and bool(answer),
        supporting=supports,
        missing_info=missing_info,
        next_query=next_query,
        status=status,
        citations=citations,
        verify_ok=verify_ok,
        answer_supported=answer_supported,
        unsupported_reasons=reasons,
        raw_model=data,
    )


def read_passages(
    *,
    question: str,
    passages: list[ReaderPassage],
    llm: LLMClient,
    max_passages: int = 10,
    max_chars: int = 12_000,
    temperature: float = 0.0,
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
    out = verify_reader_payload(data, used)
    out.usage = result.usage
    out.provider = result.provider
    out.model = result.model
    out.mode = "structured_reader"
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
