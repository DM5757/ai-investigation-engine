"""Deterministic contradiction candidates + optional LLM adjudication."""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.errors import BudgetExceeded
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
_TIME_UTC_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*UTC\b", re.IGNORECASE)
_ENTITY_TOKEN_RE = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b", re.IGNORECASE)


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


def candidate_conflicts(
    claims: list[Claim],
    *,
    question: str | None = None,
) -> list[Conflict]:
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
    # Temporal deploy-time conflicts only when the question asks about time /
    # deploy / contradictions — not for unrelated "who approved" questions.
    q = (question or "").lower()
    if re.search(r"\b(?:time|when|utc|o'?clock|contradict|deploy(?:ed|ment)?)\b", q):
        out.extend(_temporal_conflicts(claims))
    # Competing root-cause attributions across docs (JWT vs Neon pool, etc.).
    if re.search(r"\b(?:root cause|caused by|contradict|outage cause)\b", q):
        out.extend(_causal_conflicts(claims))
    return out


_CAUSE_ASSERT_RE = re.compile(
    r"(?:(?:was|were|is|are)\s+caused\s+by|caused\s+by|"
    r"root\s+cause(?:\s*\([^)]*\))?\s*:?)\s*"
    r"([^.;\n]{5,120})"
    r"|([^.!?\n]{5,100}?)\s+caused\s+"
    r"(?:cascading|timeouts?|retries|outage|disruption|failure)",
    re.IGNORECASE,
)
_CAUSE_NEG_RE = re.compile(
    r"\bnot\s+(JWT(?:\s+TTL)?|[A-Z][A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,4})",
    re.IGNORECASE,
)


def _cause_keys(text: str) -> set[str]:
    """Normalize a cause phrase into comparable content keys."""
    low = re.sub(r"[^a-z0-9\s\-]+", " ", text.lower())
    stop = {
        "a",
        "an",
        "the",
        "by",
        "of",
        "to",
        "into",
        "and",
        "or",
        "not",
        "claim",
        "claims",
        "release",
        "notes",
        "ops",
        "caused",
        "cascading",
        "retries",
    }
    keys = {
        t
        for t in re.findall(r"[a-z][a-z0-9\-]{2,}", low)
        if t not in stop and len(t) >= 3
    }
    # Collapse close variants.
    if "jwt" in keys or "ttl" in keys:
        keys.add("jwt_ttl")
    if "neon" in keys or "pool" in keys:
        keys.add("neon_pool")
    return keys


def _causal_conflicts(claims: list[Claim]) -> list[Conflict]:
    """Detect disagreeing root-cause attributions across independent docs.

    Requires shared outage/payment/auth context so unrelated causes elsewhere
    do not become false conflicts.
    """
    topic_re = re.compile(
        r"\b(?:outage|payment|auth[\s\-]?gateway|authgateway|jwt|neon)\b", re.I
    )
    asserted: list[tuple[frozenset[str], Claim]] = []
    negated: list[tuple[frozenset[str], Claim]] = []
    for claim in claims:
        if not claim.verified:
            continue
        hay = f"{claim.subject} {claim.value} {claim.quote}"
        if not topic_re.search(hay):
            continue
        for match in _CAUSE_ASSERT_RE.finditer(hay):
            phrase = next((g for g in match.groups() if g), "")
            keys = _cause_keys(phrase)
            if keys:
                asserted.append((frozenset(keys), claim))
        for match in _CAUSE_NEG_RE.finditer(hay):
            keys = _cause_keys(match.group(1))
            if keys:
                negated.append((frozenset(keys), claim))
    out: list[Conflict] = []
    # Asserted cause A vs asserted cause B on different docs with little overlap.
    for i, (keys_a, claim_a) in enumerate(asserted):
        for keys_b, claim_b in asserted[i + 1 :]:
            if claim_a.doc_id == claim_b.doc_id:
                continue
            overlap = keys_a & keys_b
            # Distinct primary mechanisms (e.g. jwt_ttl vs neon_pool).
            if overlap & {"jwt_ttl", "neon_pool"}:
                continue
            if ("jwt_ttl" in keys_a and "neon_pool" in keys_b) or (
                "neon_pool" in keys_a and "jwt_ttl" in keys_b
            ):
                out.append(
                    Conflict(
                        subject="payment_outage",
                        attribute="root_cause",
                        sides=[claim_a, claim_b],
                    )
                )
                return out
            if not overlap and len(keys_a) >= 2 and len(keys_b) >= 2:
                out.append(
                    Conflict(
                        subject="payment_outage",
                        attribute="root_cause",
                        sides=[claim_a, claim_b],
                    )
                )
                return out
    # Asserted X vs explicit "not X" across docs.
    for keys_a, claim_a in asserted:
        for keys_n, claim_n in negated:
            if claim_a.doc_id == claim_n.doc_id:
                continue
            if keys_a & keys_n:
                out.append(
                    Conflict(
                        subject="payment_outage",
                        attribute="root_cause",
                        sides=[claim_a, claim_n],
                    )
                )
                return out
    return out


_DEPLOY_TOPIC_RE = re.compile(
    r"\b(?:deploy(?:ed|ment)?|auth[\s\-]?gateway|authgateway)\b", re.I
)


def _normalize_entity_keys(text: str) -> set[str]:
    """Shared keys so AuthGateway and auth-gateway collide."""
    low = text.lower()
    keys = {m.group(0).replace("-", "").replace(" ", "") for m in _ENTITY_TOKEN_RE.finditer(low)}
    if re.search(r"auth[\s\-]?gateway|authgateway", low):
        keys.add("authgateway")
    return {k for k in keys if len(k) >= 6}


def _temporal_conflicts(claims: list[Claim]) -> list[Conflict]:
    """Detect disagreeing clock times across docs for the same deploy entity.

    Requires a shared normalized entity key (e.g. authgateway) plus deploy context
    so unrelated timestamps in different topics do not become false conflicts.
    """
    # entity_key -> list[(time, claim)]
    by_key: dict[str, list[tuple[str, Claim]]] = {}
    for claim in claims:
        if not claim.verified:
            continue
        hay = f"{claim.subject} {claim.value} {claim.quote}"
        found_times = _TIME_UTC_RE.findall(hay)
        if not found_times or not _DEPLOY_TOPIC_RE.search(hay):
            continue
        keys = _normalize_entity_keys(hay) or {"deploy"}
        for key in keys:
            for tval in found_times:
                by_key.setdefault(key, []).append((tval, claim))
    out: list[Conflict] = []
    seen: set[tuple[str, ...]] = set()
    for key, pairs in by_key.items():
        distinct_times = {t for t, _ in pairs}
        docs = {c.doc_id for _, c in pairs}
        if len(distinct_times) < 2 or len(docs) < 2:
            continue
        sides: list[Claim] = []
        used_times: set[str] = set()
        used_docs: set[str] = set()
        for tval, claim in pairs:
            if tval in used_times or claim.doc_id in used_docs:
                continue
            used_times.add(tval)
            used_docs.add(claim.doc_id)
            sides.append(
                claim.model_copy(
                    update={"attribute": "deploy_time", "value": f"{tval} UTC"}
                )
            )
            if len(sides) >= 2:
                break
        if len(sides) < 2:
            continue
        doc_key = tuple(sorted(c.doc_id for c in sides))
        if doc_key in seen:
            continue
        seen.add(doc_key)
        out.append(Conflict(subject=key, attribute="deploy_time", sides=sides))
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
        except BudgetExceeded:
            raise
        except Exception:
            updated.append(conflict)
    return updated, usage
