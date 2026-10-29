"""Investigation state machine: plan → tools → claims → answer + trace."""

from __future__ import annotations

import re
from typing import Any

from app.config import Settings, get_settings
from app.errors import BudgetExceeded, LLMUnavailable
from app.index.qdrant_store import ChunkStore
from app.investigation.aggregator import assign_source_labels
from app.investigation.contradictions import adjudicate_conflicts, candidate_conflicts
from app.investigation.extractor import claims_from_tool_payload, heuristic_claims_from_chunk
from app.investigation.planner import plan_question
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
        try:
            q = guard_question(question, self.settings.max_question_chars)
        except ValueError as exc:
            return AnswerResponse(
                status="insufficient",
                abstention_reason=str(exc),
                trace=trace.events,
            )

        with trace.stage("guard", inputs_summary=q[:120]) as bag:
            bag["outputs_summary"] = f"len={len(q)}"

        plan, plan_usage, used_llm_plan = plan_question(
            q, self.llm, max_sub_questions=self.settings.max_sub_questions
        )
        usage_total = usage_total.add(plan_usage)
        with trace.stage("plan", inputs_summary=q[:120]) as bag:
            bag["outputs_summary"] = (
                f"type={plan.question_type}; n={len(plan.sub_questions)}; llm={used_llm_plan}"
            )
            bag["tokens"] = plan_usage

        tools = ToolExecutor(
            retriever=self.retriever,
            store=self.store,
            top_k=self.settings.retrieval_top_k,
            tau_retrieval=self.settings.tau_retrieval,
            injection_downweight=self.settings.injection_downweight,
        )

        if self.llm is None:
            return self._degraded(q, plan, tools, trace, usage_total)

        focus = plan.sub_questions[0].text if plan.sub_questions else q
        try:
            self._tool_loop(q, focus, tools, trace)
        except BudgetExceeded as exc:
            with trace.stage("budget", inputs_summary=str(exc)) as bag:
                bag["outputs_summary"] = "budget_exceeded"
            return self._finalize(
                q, plan, tools, trace, usage_total, force_status="partial", degraded=True
            )
        except LLMUnavailable:
            return self._degraded(q, plan, tools, trace, usage_total)

        return self._finalize(q, plan, tools, trace, usage_total)

    def _degraded(
        self,
        question: str,
        plan: Any,
        tools: ToolExecutor,
        trace: TraceRecorder,
        usage: UsageStats,
    ) -> AnswerResponse:
        """No provider: still retrieve evidence and return llm_unavailable."""
        with trace.stage("retrieve_degraded", inputs_summary=question[:120]) as bag:
            hits = self.retriever.retrieve(question, k=self.settings.retrieval_top_k)
            for hit in hits:
                tools.state.chunk_texts[hit.chunk.chunk_id] = hit.chunk.text
                tools.state.retrieved.append(hit)
            bag["outputs_summary"] = f"hits={len(hits)}"
        preview = [
            {
                "chunk_id": h.chunk.chunk_id,
                "doc_id": h.chunk.doc_id,
                "text": h.chunk.text[:240],
                "score": h.fused_score or h.chunk.score,
            }
            for h in tools.state.retrieved[:5]
        ]
        with trace.stage("llm_unavailable") as bag:
            bag["outputs_summary"] = "no provider / provider failed"
        return AnswerResponse(
            status="llm_unavailable",
            answer=None,
            plan=plan,
            evidence_preview=preview,
            findings=list(tools.state.findings),
            abstention_reason="LLM unavailable; returning retrieved evidence only.",
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
    ) -> None:
        assert self.llm is not None
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=TOOL_LOOP_SYSTEM),
            ChatMessage(role="user", content=f"Question: {question}\nFocus: {sub_q}"),
        ]
        # Seed with one search so scripted/deterministic paths always have evidence
        seed = tools.execute(
            "search_documents",
            {"query": sub_q, "k": self.settings.retrieval_top_k},
        )
        with trace.stage("tools_seed_search", inputs_summary=sub_q[:120]) as bag:
            bag["outputs_summary"] = f"results={len(seed.get('results', []))}"

        for round_i in range(self.settings.max_tool_rounds):
            result = self.llm.chat(messages, tools=TOOL_SCHEMAS, stage="tools")
            with trace.stage(f"tools_round_{round_i}", inputs_summary=f"round={round_i}") as bag:
                bag["outputs_summary"] = (
                    f"content={bool(result.content)}; tools={len(result.tool_calls)}"
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
                if self._blocked_tool(call, tools):
                    payload = {"error": "blocked_injection_chunk"}
                else:
                    payload = tools.execute(call.name, call.arguments)
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
                built = claims_from_tool_payload(
                    data,
                    chunk_text=text,
                    chunk_id=str(cid),
                    doc_id=str(data.get("doc_id") or (finding.related_doc_ids or ["?"])[0]),
                    claim_id=finding.finding_id,
                )
                if built and built.verified:
                    claims.append(built)
        # Heuristic fallback from retrieved chunks (skip injection-flagged)
        hints = _keyword_hints(question)
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
        force_status: str | None = None,
        degraded: bool = False,
    ) -> AnswerResponse:
        claims = self._collect_claims(question, tools)
        n_ret = len(tools.state.retrieved)
        with trace.stage("extract", inputs_summary=f"n_retrieved={n_ret}") as bag:
            bag["outputs_summary"] = f"verified={sum(1 for c in claims if c.verified)}"

        conflicts = candidate_conflicts(claims)
        conflicts, adj_usage = adjudicate_conflicts(conflicts, self.llm)
        usage_total = usage_total.add(adj_usage)
        with trace.stage("contradictions") as bag:
            bag["outputs_summary"] = f"conflicts={len(conflicts)}"
            bag["tokens"] = adj_usage

        status, reason = assess_sufficiency(
            verified_claims=[c for c in claims if c.verified],
            conflicts=conflicts,
            question=question,
        )
        if force_status == "partial":
            status = "partial"
            reason = reason or "Budget exceeded; partial investigation."
        with trace.stage("sufficiency") as bag:
            bag["outputs_summary"] = f"status={status}"

        answer, citations, syn_usage, _ = synthesize_answer(
            question=question,
            status=status,
            claims=claims,
            conflicts=conflicts,
            abstention_reason=reason,
            llm=self.llm,
        )
        usage_total = usage_total.add(syn_usage)
        with trace.stage("synthesize") as bag:
            bag["outputs_summary"] = f"len={len(answer or '')}"
            bag["tokens"] = syn_usage

        answer, citations, removed, ok = verify_answer_citations(answer, citations, claims)
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
        with trace.stage("verify") as bag:
            bag["outputs_summary"] = f"ok={ok}; removed={removed}"

        return AnswerResponse(
            status=status,
            answer=answer,
            citations=citations,
            claims=claims,
            conflicts=conflicts,
            findings=list(tools.state.findings),
            plan=plan,
            abstention_reason=reason if status in ("insufficient", "llm_unavailable") else None,
            usage=usage_total,
            degraded=degraded,
            trace=trace.events,
        )


def _keyword_hints(question: str) -> list[str]:
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
    tokens = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", question) if len(t) > 3]
    hints = [t for t in tokens if t.lower() not in stop]
    return hints[:6] or tokens[:3]


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=True)
