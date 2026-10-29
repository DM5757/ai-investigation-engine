"""Gateway retry, fallback, timeout, and budget with ScriptedLLM."""

from __future__ import annotations

import pytest

from app.errors import BudgetExceeded, LLMUnavailable
from app.llm.gateway import LLMGateway
from app.llm.retry import RetryableLLMError, RetryPolicy
from app.llm.scripted import ScriptedLLM, ScriptedResponse, retryable_429
from app.llm.types import ChatMessage
from app.llm.usage import BudgetTracker
from app.schemas.evidence import UsageStats


def test_retry_then_fallback_success() -> None:
    primary = ScriptedLLM(
        [retryable_429(0.0), retryable_429(0.0), retryable_429(0.0)],
        name="primary",
    )
    secondary = ScriptedLLM(
        [ScriptedResponse(content="ok", provider="fallback")],
        name="fallback",
    )
    sleeps: list[float] = []
    gw = LLMGateway(
        [primary, secondary],
        retry_policy=RetryPolicy(max_attempts=2, base_delay_s=0.01, jitter_s=0.0),
        sleeper=sleeps.append,
    )
    result = gw.chat([ChatMessage(role="user", content="hi")], stage="test")
    assert result.content == "ok"
    assert result.provider == "fallback"
    assert sleeps  # primary retried


def test_timeout_simulation_as_retryable() -> None:
    client = ScriptedLLM(
        [RetryableLLMError("timeout: simulated"), ScriptedResponse(content="recovered")],
        name="solo",
    )
    gw = LLMGateway(
        [client],
        retry_policy=RetryPolicy(max_attempts=2, base_delay_s=0.0, jitter_s=0.0),
        sleeper=lambda _s: None,
    )
    assert gw.chat([ChatMessage(role="user", content="x")]).content == "recovered"


def test_all_providers_exhausted() -> None:
    a = ScriptedLLM([retryable_429(0.0), retryable_429(0.0)], name="a")
    b = ScriptedLLM([retryable_429(0.0), retryable_429(0.0)], name="b")
    gw = LLMGateway(
        [a, b],
        retry_policy=RetryPolicy(max_attempts=1, base_delay_s=0.0, jitter_s=0.0),
        sleeper=lambda _s: None,
    )
    with pytest.raises(LLMUnavailable):
        gw.chat([ChatMessage(role="user", content="x")])


def test_budget_exceeded() -> None:
    client = ScriptedLLM(
        [
            ScriptedResponse(usage=UsageStats(calls=1, total_tokens=10)),
            ScriptedResponse(usage=UsageStats(calls=1, total_tokens=10)),
        ]
    )
    gw = LLMGateway(
        [client],
        budget=BudgetTracker(max_calls=1, max_tokens=10_000, max_wall_clock_s=60),
        retry_policy=RetryPolicy(max_attempts=1),
        sleeper=lambda _s: None,
    )
    gw.chat([ChatMessage(role="user", content="1")])
    with pytest.raises(BudgetExceeded):
        gw.chat([ChatMessage(role="user", content="2")])
