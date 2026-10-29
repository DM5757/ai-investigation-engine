"""Retry helpers: exponential backoff with jitter and Retry-After."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for provider-level retries."""

    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter_s: float = 0.25


class RetryableLLMError(Exception):
    """Transient provider failure (429, 5xx, timeout)."""

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class FatalLLMError(Exception):
    """Non-retryable provider failure (401, bad request)."""


def compute_delay(
    attempt: int,
    policy: RetryPolicy,
    *,
    retry_after_s: float | None = None,
) -> float:
    """Return sleep seconds for the given 0-based attempt index."""
    if retry_after_s is not None and retry_after_s > 0:
        return float(min(retry_after_s, policy.max_delay_s))
    delay = policy.base_delay_s * (2**attempt)
    delay = min(delay, policy.max_delay_s)
    delay += float(random.uniform(0.0, policy.jitter_s))
    return float(delay)


def with_retries(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn`` with exponential backoff on ``RetryableLLMError``."""
    last: RetryableLLMError | None = None
    for attempt in range(policy.max_attempts):
        try:
            return fn()
        except RetryableLLMError as exc:
            last = exc
            if attempt + 1 >= policy.max_attempts:
                break
            sleeper(compute_delay(attempt, policy, retry_after_s=exc.retry_after_s))
    assert last is not None
    raise last
