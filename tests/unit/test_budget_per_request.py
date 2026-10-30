"""Per-request LLM budget isolation across consecutive investigations."""

from __future__ import annotations

import json

from app.config import Settings
from app.investigation.engine import InvestigationEngine
from app.llm.gateway import LLMGateway
from app.llm.retry import RetryPolicy
from app.llm.scripted import ScriptedLLM, ScriptedResponse
from app.llm.usage import BudgetTracker
from app.schemas.evidence import UsageStats
from tests.integration.test_investigation_scripted import _build_stack


def _plan() -> ScriptedResponse:
    return ScriptedResponse(
        content=json.dumps(
            {
                "question_type": "factual",
                "sub_questions": [
                    {
                        "id": "q1",
                        "text": "What caused PaymentService disruptions in March?",
                        "depends_on": [],
                    }
                ],
                "expected_answer_shape": "short_paragraph",
            }
        ),
        usage=UsageStats(calls=1, total_tokens=10),
    )


def _synth() -> ScriptedResponse:
    return ScriptedResponse(
        content=(
            "The March 12 auth-gateway deploy caused PaymentService disruptions [S1]."
        ),
        usage=UsageStats(calls=1, total_tokens=10),
    )


def test_consecutive_investigations_reset_budget() -> None:
    """Same gateway instance must serve multiple questions without wall-clock leak."""
    _, store, retriever = _build_stack(["doc_a", "doc_b"])
    # Each investigate: plan + tools + synthesize = 3 calls. Budget max_calls=3
    # would fail the second question without a per-request reset.
    responses = [
        _plan(),
        ScriptedResponse(content=None, tool_calls=[], usage=UsageStats(calls=1, total_tokens=5)),
        _synth(),
        _plan(),
        ScriptedResponse(content=None, tool_calls=[], usage=UsageStats(calls=1, total_tokens=5)),
        _synth(),
    ]
    client = ScriptedLLM(responses)
    gw = LLMGateway(
        [client],
        budget=BudgetTracker(max_calls=3, max_tokens=50_000, max_wall_clock_s=120),
        retry_policy=RetryPolicy(max_attempts=1),
        sleeper=lambda _s: None,
    )
    eng = InvestigationEngine(
        retriever,
        store,
        llm=gw,
        settings=Settings(retrieval_top_k=5, max_tool_rounds=2, tau_relative=0.0),
    )
    first = eng.investigate("What caused PaymentService disruptions in March?")
    second = eng.investigate(
        "What caused PaymentService disruptions in March according to documents?"
    )
    assert first.status in ("answered", "partial", "conflicting")
    assert second.status in ("answered", "partial", "conflicting")
    assert first.usage.calls >= 1
    assert second.usage.calls >= 1


def test_budget_exhaustion_is_llm_unavailable_not_fake_answer() -> None:
    _, store, retriever = _build_stack(["doc_a", "doc_b"])
    client = ScriptedLLM(
        [
            _plan(),
            # tools call will exhaust budget (max_calls=1 already consumed by plan)
        ]
    )
    gw = LLMGateway(
        [client],
        budget=BudgetTracker(max_calls=1, max_tokens=50_000, max_wall_clock_s=120),
        retry_policy=RetryPolicy(max_attempts=1),
        sleeper=lambda _s: None,
    )
    eng = InvestigationEngine(
        retriever,
        store,
        llm=gw,
        settings=Settings(retrieval_top_k=5, max_tool_rounds=2, tau_relative=0.0),
    )
    result = eng.investigate("What caused PaymentService disruptions in March?")
    assert result.status == "llm_unavailable"
    assert result.degraded is True
    assert result.answer is None
    assert result.abstention_reason
    assert "budget" in (result.abstention_reason or "").lower()
    assert result.evidence_preview
