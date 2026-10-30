"""Gateway must fail-fast on daily quota and not burn retries."""

from __future__ import annotations

import pytest

from app.errors import LLMUnavailable
from app.llm.failure import FailureKind
from app.llm.gateway import LLMGateway
from app.llm.retry import FatalLLMError, RetryPolicy
from app.llm.scripted import ScriptedLLM, ScriptedResponse
from app.llm.types import ChatMessage
from app.llm.usage import BudgetTracker


def test_daily_quota_skips_retries_and_fails_over() -> None:
    primary = ScriptedLLM(
        [
            FatalLLMError(
                "requests per day exceeded",
                kind=FailureKind.DAILY_QUOTA,
                provider="primary",
            ),
            FatalLLMError(
                "should not be called",
                kind=FailureKind.DAILY_QUOTA,
                provider="primary",
            ),
        ],
        name="primary",
    )
    secondary = ScriptedLLM(
        [ScriptedResponse(content="ok", provider="fallback")],
        name="fallback",
    )
    sleeps: list[float] = []
    gw = LLMGateway(
        [primary, secondary],
        retry_policy=RetryPolicy(max_attempts=3, base_delay_s=1.0, jitter_s=0.0),
        sleeper=sleeps.append,
        budget=BudgetTracker(max_wall_clock_s=60),
    )
    gw.begin_request()
    result = gw.chat([ChatMessage(role="user", content="hi")], stage="test")
    assert result.content == "ok"
    assert result.provider == "fallback"
    assert sleeps == []
    assert len(primary.calls) == 1


def test_daily_quota_both_providers_fail_fast() -> None:
    a = ScriptedLLM(
        [
            FatalLLMError(
                "tokens per day",
                kind=FailureKind.DAILY_QUOTA,
                provider="a",
            )
        ],
        name="a",
    )
    b = ScriptedLLM(
        [
            FatalLLMError(
                "quota exceeded",
                kind=FailureKind.DAILY_QUOTA,
                provider="b",
            )
        ],
        name="b",
    )
    sleeps: list[float] = []
    gw = LLMGateway(
        [a, b],
        retry_policy=RetryPolicy(max_attempts=5, base_delay_s=2.0, jitter_s=0.0),
        sleeper=sleeps.append,
    )
    gw.begin_request()
    with pytest.raises(LLMUnavailable) as exc:
        gw.chat([ChatMessage(role="user", content="x")])
    assert "daily_quota" in str(exc.value)
    assert sleeps == []
    # Second chat in same request should skip already-dead providers immediately.
    with pytest.raises(LLMUnavailable):
        gw.chat([ChatMessage(role="user", content="y")])
    assert len(a.calls) == 1
    assert len(b.calls) == 1
