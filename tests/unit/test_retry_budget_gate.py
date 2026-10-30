"""Retries must honour wall-clock budget between attempts."""

from __future__ import annotations

import pytest

from app.errors import BudgetExceeded
from app.llm.retry import RetryableLLMError, RetryPolicy, with_retries
from app.llm.usage import BudgetTracker


def test_with_retries_stops_when_budget_exhausted() -> None:
    budget = BudgetTracker(max_calls=20, max_tokens=50_000, max_wall_clock_s=0.0)
    calls = {"n": 0}

    def boom() -> str:
        calls["n"] += 1
        raise RetryableLLMError("429")

    with pytest.raises(BudgetExceeded):
        with_retries(
            boom,
            RetryPolicy(max_attempts=5, base_delay_s=0.01, max_delay_s=0.01, jitter_s=0.0),
            before_attempt=budget.check,
            sleeper=lambda _s: None,
        )
    assert calls["n"] == 0


def test_with_retries_skips_sleep_past_remaining_budget() -> None:
    budget = BudgetTracker(max_calls=20, max_tokens=50_000, max_wall_clock_s=0.2)
    calls = {"n": 0}
    sleeps: list[float] = []

    def boom() -> str:
        calls["n"] += 1
        raise RetryableLLMError("429", retry_after_s=30.0)

    with pytest.raises(RetryableLLMError):
        with_retries(
            boom,
            RetryPolicy(max_attempts=5, base_delay_s=1.0, max_delay_s=30.0, jitter_s=0.0),
            before_attempt=budget.check,
            remaining_s=budget.remaining_s,
            sleeper=sleeps.append,
        )
    assert calls["n"] == 1
    assert sleeps == []
