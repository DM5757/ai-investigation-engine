"""Retry helpers: exponential backoff with jitter and Retry-After."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from app.llm.failure import FailureKind, is_non_retryable

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for provider-level retries."""

    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter_s: float = 0.25


class RetryableLLMError(Exception):
    """Transient provider failure (RPM/TPM 429, 5xx, timeout)."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_s: float | None = None,
        kind: FailureKind = FailureKind.UNKNOWN,
        provider: str = "",
    ) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s
        self.kind = kind
        self.provider = provider


class FatalLLMError(Exception):
    """Non-retryable provider failure (daily quota, auth, context overflow)."""

    def __init__(
        self,
        message: str,
        *,
        kind: FailureKind = FailureKind.UNKNOWN,
        provider: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.provider = provider


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
    before_attempt: Callable[[], None] | None = None,
    remaining_s: Callable[[], float] | None = None,
) -> T:
    """Call ``fn`` with exponential backoff on ``RetryableLLMError``.

    Optional ``before_attempt`` runs before each try (and before backoff sleep)
    so callers can enforce wall-clock budgets instead of hanging past them.

    Optional ``remaining_s`` skips further retries when the next delay would
    exceed the remaining budget (fail over / fail fast instead).
    """
    last: RetryableLLMError | None = None
    for attempt in range(policy.max_attempts):
        if before_attempt is not None:
            before_attempt()
        try:
            return fn()
        except FatalLLMError:
            raise
        except RetryableLLMError as exc:
            last = exc
            if is_non_retryable(exc.kind):
                raise FatalLLMError(str(exc), kind=exc.kind, provider=exc.provider) from exc
            if attempt + 1 >= policy.max_attempts:
                break
            delay = compute_delay(attempt, policy, retry_after_s=exc.retry_after_s)
            if remaining_s is not None:
                left = remaining_s()
                if left <= 0.05:
                    break
                if delay > left:
                    # Prefer failing over / exhausting rather than sleeping past budget.
                    break
            if before_attempt is not None:
                before_attempt()
            sleeper(delay)
    assert last is not None
    raise last
