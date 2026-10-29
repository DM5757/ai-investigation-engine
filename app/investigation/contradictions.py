"""Deterministic contradiction candidates + optional LLM adjudication."""

from __future__ import annotations

from pydantic import BaseModel

from app.investigation.aggregator import aggregate_claims
from app.llm.json_repair import parse_model
from app.llm.types import ChatMessage, LLMClient
from app.schemas.evidence import Claim, Conflict, UsageStats

_NEG = ("zero", "no ", "none", "unaffected", "healthy", "without", "never")
_POS = (
    "caused",
    "spiked",
    "disrupted",
    "disruption",
    "incident",
    "timeout",
    "failed",
    "outage",
)


def _values_conflict(a: str, b: str) -> bool:
    """True only for clear polarity / numeric disagreement (not mere paraphrase)."""
    na = " ".join(a.lower().split())
    nb = " ".join(b.lower().split())
    if na == nb:
        return False
    try:
        if float(na.replace(",", "")) != float(nb.replace(",", "")):
            return True
    except ValueError:
        pass
    a_neg = any(x in na for x in _NEG)
    b_neg = any(x in nb for x in _NEG)
    a_pos = any(x in na for x in _POS)
    b_pos = any(x in nb for x in _POS)
    return (a_neg and b_pos) or (b_neg and a_pos)


def candidate_conflicts(claims: list[Claim]) -> list[Conflict]:
    """Build conflicts when independent docs disagree on same subject/attribute."""
    out: list[Conflict] = []
    for (subject, attribute), group in aggregate_claims(claims).items():
        if len(group) < 2:
            continue
        # Pairwise across different docs with differing values
        sides: list[Claim] = []
        for claim in group:
            if any(
                c.doc_id != claim.doc_id and _values_conflict(c.value, claim.value)
                for c in group
            ):
                sides.append(claim)
        # Deduplicate while preserving order
        uniq: list[Claim] = []
        seen: set[str] = set()
        for claim in sides:
            if claim.claim_id in seen:
                continue
            seen.add(claim.claim_id)
            uniq.append(claim)
        docs = {c.doc_id for c in uniq}
        values = {" ".join(c.value.lower().split()) for c in uniq}
        if len(docs) >= 2 and len(values) >= 2:
            out.append(
                Conflict(subject=subject, attribute=attribute, sides=uniq)
            )
    return out


class _Adjudication(BaseModel):
    note: str


def adjudicate_conflicts(
    conflicts: list[Conflict],
    llm: LLMClient | None,
) -> tuple[list[Conflict], UsageStats]:
    """Optionally ask LLM for a non-binding adjudication note."""
    if not conflicts or llm is None:
        return conflicts, UsageStats()
    usage = UsageStats()
    updated: list[Conflict] = []
    for conflict in conflicts:
        summary = "; ".join(
            f"{c.doc_id}:{c.value}" for c in conflict.sides
        )
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "Summarize the disagreement in one sentence. "
                    "Do not pick a winner. Return JSON {\"note\": \"...\"}."
                ),
            ),
            ChatMessage(
                role="user",
                content=f"{conflict.subject}.{conflict.attribute}: {summary}",
            ),
        ]
        try:
            result = llm.chat(
                messages,
                response_format={"type": "json_object"},
                stage="contradictions",
            )
            usage = usage.add(result.usage)
            note = parse_model(result.content or "", _Adjudication).note
            updated.append(conflict.model_copy(update={"adjudication": note}))
        except Exception:
            updated.append(conflict)
    return updated, usage
