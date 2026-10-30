"""Investigation state machine: plan → tools → claims → answer + trace."""

from __future__ import annotations

import re
import time
from typing import Any

from app.config import Settings, get_settings
from app.errors import BudgetExceeded, LLMUnavailable
from app.index.qdrant_store import ChunkStore
from app.investigation.aggregator import assign_source_labels
from app.investigation.contradictions import adjudicate_conflicts, candidate_conflicts
from app.investigation.entities import bridge_entity_queries, extract_focus_entities
from app.investigation.extractor import claims_from_tool_payload, heuristic_claims_from_chunk
from app.investigation.planner import plan_question
from app.investigation.question_focus import (
    evidence_text_support,
    extract_question_focus,
    filter_claims_for_question,
)
from app.investigation.sufficiency import assess_sufficiency
from app.investigation.synthesizer import synthesize_answer
from app.investigation.tools import TOOL_SCHEMAS, ToolExecutor
from app.investigation.trace import TraceRecorder
from app.investigation.verifier import downgrade_status, verify_answer_citations
from app.llm.prompts.tools import TOOL_LOOP_SYSTEM
from app.llm.types import ChatMessage, LLMClient, ToolCall
from app.retrieval.hybrid import HybridRetriever
from app.schemas.evidence import AnswerResponse, Claim, UsageStats

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def guard_question(question: str, max_chars: int) -> str:
    """Strip controls and enforce length; raise ValueError if empty."""
    cleaned = _CONTROL_RE.sub("", question).strip()
    if not cleaned:
        raise ValueError("empty question")
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


class InvestigationEngine:
    """Hand-written multi-stage investigation orchestrator."""

    def __init__(
        self,
        retriever: HybridRetriever,
        store: ChunkStore,
        llm: LLMClient | None,
        settings: Settings | None = None,
    ) -> None:
        self.retriever = retriever
        self.store = store
        self.llm = llm
        self.settings = settings or get_settings()

    def investigate(self, question: str) -> AnswerResponse:
        trace = TraceRecorder()
        usage_total = UsageStats()
        t_request = time.perf_counter()
        try:
            q = guard_question(question, self.settings.max_question_chars)
        except ValueError as exc:
            return AnswerResponse(
                status="insufficient",
                abstention_reason=str(exc),
                trace=trace.events,
            )

        # Independent per-request budget (does not leak across questions/users).
        self._begin_request_budget()

        with trace.stage("guard", inputs_summary=q[:120]) as bag:
            bag["outputs_summary"] = f"len={len(q)}"

        tools = ToolExecutor(
            retriever=self.retriever,
            store=self.store,
            top_k=self.settings.retrieval_top_k,
            tau_retrieval=self.settings.tau_retrieval,
            tau_relative=self.settings.tau_relative,
            injection_downweight=self.settings.injection_downweight,
            before_call=self._budget_check,
        )

        if self.llm is None:
            response = self._degraded(
                q,
                None,
                tools,
                trace,
                usage_total,
                reason="LLM unavailable; returning retrieved evidence only.",
            )
            return self._finish(response, trace, t_request)

        try:
            with trace.stage("plan", inputs_summary=q[:120]) as bag:
                plan, plan_usage, used_llm_plan = plan_question(
                    q, self.llm, max_sub_questions=self.settings.max_sub_questions
                )
                bag["outputs_summary"] = (
                    f"type={plan.question_type}; n={len(plan.sub_questions)}; "
                    f"llm={used_llm_plan}"
                )
                bag["tokens"] = plan_usage
            usage_total = usage_total.add(plan_usage)
        except BudgetExceeded as exc:
            with trace.stage("budget", inputs_summary=str(exc)) as bag:
                bag["outputs_summary"] = "budget_exceeded_during_plan"
            return self._finish(
                self._degraded(
                    q,
                    None,
                    tools,
                    trace,
                    usage_total,
                    reason=(
                        f"Local investigation budget exceeded during planning ({exc}). "
                        "Retrieved evidence only; no synthesized answer."
                    ),
                ),
                trace,
                t_request,
            )
        except LLMUnavailable as exc:
            return self._finish(
                self._degraded(
                    q,
                    None,
                    tools,
                    trace,
                    usage_total,
                    reason=(
                        "LLM provider unavailable after retries/fallback "
                        f"({self._sanitize_fail(exc)}); returning retrieved evidence only."
                    ),
                ),
                trace,
                t_request,
            )

        focus = plan.sub_questions[0].text if plan.sub_questions else q
        # Keep the full question as tool focus for multi-entity comparisons so
        # the model does not narrow to a single campus/branch peer.
        if len(extract_focus_entities(q)) >= 2:
            focus = q
        tool_usage_box: dict[str, UsageStats] = {"usage": UsageStats()}
        try:
            self._tool_loop(q, focus, tools, trace, tool_usage_box)
            usage_total = usage_total.add(tool_usage_box["usage"])
        except BudgetExceeded as exc:
            usage_total = usage_total.add(tool_usage_box["usage"])
            with trace.stage("budget", inputs_summary=str(exc)) as bag:
                bag["outputs_summary"] = "budget_exceeded_during_tools"
            return self._finish(
                self._degraded(
                    q,
                    plan,
                    tools,
                    trace,
                    usage_total,
                    reason=(
                        f"Local investigation budget exceeded during tool use ({exc}). "
                        "Retrieved evidence only; no synthesized answer."
                    ),
                ),
                trace,
                t_request,
            )
        except LLMUnavailable as exc:
            usage_total = usage_total.add(tool_usage_box["usage"])
            return self._finish(
                self._degraded(
                    q,
                    plan,
                    tools,
                    trace,
                    usage_total,
                    reason=(
                        "LLM provider unavailable after retries/fallback "
                        f"({self._sanitize_fail(exc)}); returning retrieved evidence only."
                    ),
                ),
                trace,
                t_request,
            )

        try:
            return self._finish(
                self._finalize(q, plan, tools, trace, usage_total),
                trace,
                t_request,
            )
        except BudgetExceeded as exc:
            with trace.stage("budget", inputs_summary=str(exc)) as bag:
                bag["outputs_summary"] = "budget_exceeded_during_finalize"
            return self._finish(
                self._degraded(
                    q,
                    plan,
                    tools,
                    trace,
                    usage_total,
                    reason=(
                        f"Local investigation budget exceeded during synthesis ({exc}). "
                        "Retrieved evidence only; no synthesized answer."
                    ),
                ),
                trace,
                t_request,
            )
        except LLMUnavailable as exc:
            return self._finish(
                self._degraded(
                    q,
                    plan,
                    tools,
                    trace,
                    usage_total,
                    reason=(
                        "LLM provider unavailable after retries/fallback "
                        f"({self._sanitize_fail(exc)}); returning retrieved evidence only."
                    ),
                ),
                trace,
                t_request,
            )

    def _finish(
        self,
        response: AnswerResponse,
        trace: TraceRecorder,
        t_request: float,
    ) -> AnswerResponse:
        """Attach total request latency without mutating nested stage clocks."""
        total_ms = (time.perf_counter() - t_request) * 1000.0
        # Avoid double-counting if already finished (idempotent).
        if not any(e.stage == "request" for e in response.trace):
            failures = []
            last = getattr(self.llm, "last_failures", None)
            if isinstance(last, list):
                failures = list(last)[-6:]
            trace.append(
                "request",
                inputs_summary="",
                outputs_summary=f"status={response.status}",
                latency_ms=total_ms,
                tokens=response.usage,
                extra={
                    "total_ms": round(total_ms, 3),
                    "stage_ms": {
                        e.stage: round(float(e.latency_ms), 3) for e in response.trace
                    },
                    "provider_failures": failures,
                },
            )
            response.trace = list(trace.events)
        return response

    @staticmethod
    def _sanitize_fail(exc: BaseException) -> str:
        text = " ".join(str(exc).split())
        return text[:160]

    def _begin_request_budget(self) -> None:
        begin = getattr(self.llm, "begin_request", None)
        if callable(begin):
            begin()
            return
        budget = getattr(self.llm, "budget", None)
        reset = getattr(budget, "reset", None)
        if callable(reset):
            reset()

    def _budget_check(self) -> None:
        """Enforce wall-clock during retrieval/tools without applying LLM call caps.

        Call/token limits remain gated by the LLM gateway. Retrieval must still
        stop when the request deadline is reached so clients do not hang.
        """
        budget = getattr(self.llm, "budget", None)
        if budget is None:
            return
        max_wall = getattr(budget, "max_wall_clock_s", None)
        elapsed_fn = getattr(budget, "elapsed_s", None)
        if max_wall is None or not callable(elapsed_fn):
            return
        if float(elapsed_fn()) >= float(max_wall):
            raise BudgetExceeded(f"wall clock budget exceeded ({max_wall}s)")

    def _degraded(
        self,
        question: str,
        plan: Any,
        tools: ToolExecutor,
        trace: TraceRecorder,
        usage: UsageStats,
        *,
        reason: str,
    ) -> AnswerResponse:
        """Provider/budget failure: retrieve evidence preview, do not fake an answer."""
        if not tools.state.retrieved:
            with trace.stage("retrieve_degraded", inputs_summary=question[:120]) as bag:
                # Intentionally skip the request budget gate: previews remain useful
                # after budget/provider failure and must not raise BudgetExceeded here.
                hits = self.retriever.retrieve(
                    question, k=self.settings.retrieval_top_k
                )
                for hit in hits:
                    tools.state.chunk_texts[hit.chunk.chunk_id] = hit.chunk.text
                    tools.state.retrieved.append(hit)
                bag["outputs_summary"] = f"hits={len(hits)}"
                bag["extra"] = dict(getattr(self.retriever, "last_timings", {}) or {})

        focus = extract_question_focus(question)
        ranked = sorted(
            tools.state.retrieved,
            key=lambda h: evidence_text_support(
                h.chunk.text, h.chunk.title, focus
            ),
            reverse=True,
        )
        # Require claim-level focus support so missing-entity questions do not
        # surface weak lexical neighbours (e.g. "Alien Investigations" for
        # "Roanoke colony") as if they were supporting citations.
        min_preview_support = float(self.settings.claim_min_support)
        preview = []
        for h in ranked[:8]:
            support = evidence_text_support(h.chunk.text, h.chunk.title, focus)
            if support < min_preview_support:
                continue
            preview.append(
                {
                    "chunk_id": h.chunk.chunk_id,
                    "doc_id": h.chunk.doc_id,
                    "title": h.chunk.title,
                    "text": h.chunk.text[:240],
                    "score": h.fused_score or h.chunk.score,
                    "focus_support": round(support, 3),
                }
            )
            if len(preview) >= 5:
                break
        with trace.stage("llm_unavailable") as bag:
            bag["outputs_summary"] = reason[:160]
            failures = getattr(self.llm, "last_failures", None)
            if isinstance(failures, list) and failures:
                bag["extra"] = {"provider_failures": list(failures)[-6:]}
        return AnswerResponse(
            status="llm_unavailable",
            answer=None,
            plan=plan,
            evidence_preview=preview,
            findings=list(tools.state.findings),
            abstention_reason=reason,
            usage=usage,
            degraded=True,
            trace=trace.events,
        )

    def _tool_loop(
        self,
        question: str,
        sub_q: str,
        tools: ToolExecutor,
        trace: TraceRecorder,
        usage_box: dict[str, UsageStats],
    ) -> None:
        assert self.llm is not None
        # Seed retrieval: for multi-entity / comparison questions, search each
        # named entity so peer documents are covered before the tool loop.
        # Include results in the user message (not a synthetic tool turn) so Gemini
        # OpenAI-compat thought_signature requirements are not violated.
        entities = extract_focus_entities(question)
        seed_queries = _seed_queries(question, sub_q, entities)
        seed_results: list[dict[str, Any]] = []
        with trace.stage("tools_seed_search", inputs_summary=sub_q[:120]) as bag:
            for sq in seed_queries:
                part = tools.execute(
                    "search_documents",
                    {"query": sq, "k": self.settings.retrieval_top_k},
                )
                seed_results.append(
                    {
                        "query": sq,
                        "results": part.get("results", []),
                        "cache_hit": part.get("cache_hit", False),
                    }
                )
            n_hits = sum(len(p.get("results", [])) for p in seed_results)
            bag["outputs_summary"] = (
                f"queries={len(seed_queries)}; results={n_hits}; "
                f"entities={entities[:3]}"
            )
            bag["extra"] = {
                "seed_queries": seed_queries,
                "timings": dict(tools.last_timings),
            }

        # Multi-hop bridge: search entities mentioned in evidence but not yet retrieved.
        bridge_results: list[dict[str, Any]] = []
        bridges = bridge_entity_queries(
            question=question,
            retrieved_titles=[
                h.chunk.title or "" for h in tools.state.retrieved if h.chunk.title
            ],
            retrieved_texts=[h.chunk.text for h in tools.state.retrieved[:10]],
            known_entities=entities,
            max_bridges=2,
        )
        if bridges:
            with trace.stage("tools_bridge_search", inputs_summary=str(bridges)[:120]) as bag:
                for bq in bridges:
                    part = tools.execute(
                        "search_documents",
                        {"query": bq, "k": self.settings.retrieval_top_k},
                    )
                    bridge_results.append(
                        {
                            "query": bq,
                            "results": part.get("results", []),
                            "cache_hit": part.get("cache_hit", False),
                        }
                    )
                bag["outputs_summary"] = (
                    f"bridges={bridges}; "
                    f"results={sum(len(p.get('results', [])) for p in bridge_results)}"
                )

        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=TOOL_LOOP_SYSTEM),
            ChatMessage(
                role="user",
                content=(
                    f"Question: {question}\nFocus: {sub_q}\n"
                    f"Named entities to cover: {entities or ['(none detected)']}\n"
                    "Seed search_documents results (reuse when relevant; "
                    "prefer exact-title documents over similarly named campuses/"
                    "branches):\n"
                    f"{_json({'seeds': seed_results, 'bridges': bridge_results})}"
                ),
            ),
        ]

        for round_i in range(self.settings.max_tool_rounds):
            with trace.stage(
                f"tools_llm_round_{round_i}", inputs_summary=f"round={round_i}"
            ) as bag:
                result = self.llm.chat(messages, tools=TOOL_SCHEMAS, stage="tools")
                usage_box["usage"] = usage_box["usage"].add(result.usage)
                bag["outputs_summary"] = (
                    f"content={bool(result.content)}; tools={len(result.tool_calls)}; "
                    f"provider={result.provider}"
                )
                bag["tokens"] = result.usage
            if not result.tool_calls:
                break
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=result.content,
                    tool_calls=result.tool_calls,
                )
            )
            for call in result.tool_calls:
                with trace.stage(
                    f"tool_{call.name}",
                    inputs_summary=str(call.arguments)[:120],
                ) as bag:
                    if self._blocked_tool(call, tools):
                        payload = {"error": "blocked_injection_chunk"}
                    else:
                        payload = tools.execute(call.name, call.arguments)
                    bag["outputs_summary"] = (
                        f"keys={sorted(payload.keys())[:6]}; err={bool(payload.get('error'))}"
                    )
                    if tools.last_timings:
                        bag["extra"] = dict(tools.last_timings)
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=_json(payload),
                        tool_call_id=call.id,
                    )
                )
            if any(c.name == "record_finding" for c in result.tool_calls):
                break

    def _blocked_tool(self, call: ToolCall, tools: ToolExecutor) -> bool:
        chunk_id = str(call.arguments.get("chunk_id", ""))
        return bool(chunk_id) and chunk_id in tools.state.flagged_chunk_ids

    def _collect_claims(self, question: str, tools: ToolExecutor) -> list[Claim]:
        claims: list[Claim] = []
        # From record_finding structured hints (subject/attribute/value/quote JSON)
        for finding in tools.state.findings:
            try:
                import json

                data = json.loads(finding.text)
            except Exception:
                data = None
            if isinstance(data, dict) and data.get("quote"):
                cid = (data.get("chunk_id") or (finding.related_chunk_ids or ["?"])[0])
                text = tools.state.chunk_texts.get(str(cid), "")
                title = None
                for hit in tools.state.retrieved:
                    if hit.chunk.chunk_id == str(cid):
                        title = hit.chunk.title
                        break
                built = claims_from_tool_payload(
                    data,
                    chunk_text=text,
                    chunk_id=str(cid),
                    doc_id=str(data.get("doc_id") or (finding.related_doc_ids or ["?"])[0]),
                    claim_id=finding.finding_id,
                    source_title=title,
                )
                if built and built.verified:
                    claims.append(built)
        # Heuristic fallback from retrieved chunks (skip injection-flagged).
        # Prefer hints that actually appear in retrieved text so long question
        # tokens (e.g. "disruptions") do not crowd out domain terms ("payment").
        corpus = " ".join(
            h.chunk.text for h in tools.state.retrieved if h.chunk.chunk_id
        )
        hints = _keyword_hints(question, prefer_in_text=corpus)
        for hit in tools.state.retrieved:
            if hit.chunk.chunk_id in tools.state.flagged_chunk_ids:
                continue
            for hint in hints:
                claims.extend(
                    heuristic_claims_from_chunk(
                        chunk_id=hit.chunk.chunk_id,
                        doc_id=hit.chunk.doc_id,
                        text=hit.chunk.text,
                        subject_hint=hint,
                        claim_prefix=f"h-{hit.chunk.chunk_id}-{hint}",
                        source_title=hit.chunk.title,
                    )
                )
        # Deduplicate by quote
        seen: set[str] = set()
        uniq: list[Claim] = []
        for claim in claims:
            key = claim.quote.lower()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(claim)
        return assign_source_labels(uniq)

    def _finalize(
        self,
        question: str,
        plan: Any,
        tools: ToolExecutor,
        trace: TraceRecorder,
        usage_total: UsageStats,
        *,
        degraded: bool = False,
    ) -> AnswerResponse:
        n_ret = len(tools.state.retrieved)
        with trace.stage("extract", inputs_summary=f"n_retrieved={n_ret}") as bag:
            raw_claims = self._collect_claims(question, tools)
            supporting, _weak, focus = filter_claims_for_question(
                [c for c in raw_claims if c.verified],
                question,
                min_support=self.settings.claim_min_support,
            )
            claims = assign_source_labels(supporting)
            bag["outputs_summary"] = (
                f"verified={len(claims)}; raw={sum(1 for c in raw_claims if c.verified)}; "
                f"focus_phrases={list(focus.phrases)[:3]}"
            )

        with trace.stage("contradictions") as bag:
            conflicts = candidate_conflicts(claims)
            conflicts, adj_usage = adjudicate_conflicts(conflicts, self.llm)
            usage_total = usage_total.add(adj_usage)
            bag["outputs_summary"] = f"conflicts={len(conflicts)}"
            bag["tokens"] = adj_usage

        with trace.stage("sufficiency") as bag:
            status, reason = assess_sufficiency(
                verified_claims=claims,
                conflicts=conflicts,
                question=question,
                focus=focus,
                min_support=self.settings.claim_min_support,
            )
            bag["outputs_summary"] = f"status={status}"

        with trace.stage("synthesize") as bag:
            answer, citations, syn_usage, _ = synthesize_answer(
                question=question,
                status=status,
                claims=claims,
                conflicts=conflicts,
                abstention_reason=reason,
                llm=self.llm,
            )
            usage_total = usage_total.add(syn_usage)
            bag["outputs_summary"] = f"len={len(answer or '')}"
            bag["tokens"] = syn_usage

        with trace.stage("verify") as bag:
            answer, citations, removed, ok = verify_answer_citations(
                answer, citations, claims
            )
            if not ok:
                # One regeneration attempt via deterministic synthesizer
                answer2, citations2, _, _ = synthesize_answer(
                    question=question,
                    status=status,
                    claims=claims,
                    conflicts=conflicts,
                    abstention_reason=reason,
                    llm=None,
                )
                answer, citations, removed, ok = verify_answer_citations(
                    answer2, citations2, claims
                )
                status = downgrade_status(status, citation_failed=not ok or bool(removed))
            bag["outputs_summary"] = f"ok={ok}; removed={removed}; cites={len(citations)}"

        return AnswerResponse(
            status=status,
            answer=answer,
            citations=citations,
            claims=claims,
            conflicts=conflicts,
            findings=list(tools.state.findings),
            plan=plan,
            abstention_reason=reason
            if status in ("insufficient", "llm_unavailable", "partial")
            else None,
            usage=usage_total,
            degraded=degraded,
            trace=trace.events,
        )


def _seed_queries(question: str, sub_q: str, entities: list[str]) -> list[str]:
    """Build a small set of seed retrieval queries for multi-hop coverage."""
    queries: list[str] = []
    if len(entities) >= 2:
        queries.extend(entities[:3])
    focus = sub_q.strip() or question.strip()
    if focus and focus.lower() not in {q.lower() for q in queries}:
        queries.append(focus)
    if not queries:
        queries.append(question.strip())
    # De-dupe while preserving order
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        key = q.lower()
        if not q or key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out[:4]


def _keyword_hints(question: str, *, prefer_in_text: str | None = None) -> list[str]:
    stop = {
        "what",
        "which",
        "when",
        "where",
        "does",
        "were",
        "from",
        "that",
        "this",
        "with",
        "about",
        "have",
        "been",
        "caused",
        "cause",
        "according",
        "there",
        "their",
        "into",
    }
    focus = extract_question_focus(question)
    hints: list[str] = []
    for phrase in focus.phrases:
        hints.append(phrase)
        hints.extend(
            p for p in re.split(r"[\s\-–—]+", phrase) if len(p) > 3 and p.lower() not in stop
        )
    for tok in focus.tokens:
        if tok not in stop and tok not in {h.lower() for h in hints}:
            hints.append(tok)
    # Prefer multi-token / longer hints, then ones attested in retrieved text.
    corpus = (prefer_in_text or "").lower()

    def _rank(h: str) -> tuple[int, int, int, int]:
        low = h.lower()
        in_corpus = 1 if corpus and low in corpus else 0
        return (-in_corpus, -len(h.split()), -len(h), 0)

    hints = sorted(dict.fromkeys(hints), key=_rank)
    selected = hints[:12]
    if selected:
        return selected
    return [
        t for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", question) if len(t) > 3
    ][:6]


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=True)
