"""Provider failure classification for retry vs fail-fast."""

from __future__ import annotations

from app.llm.failure import FailureKind, classify_message, is_non_retryable


def test_daily_quota_not_retryable() -> None:
    kind = classify_message(
        "Rate limit reached for model. Limit 1000 requests per day. Please try again tomorrow.",
        status=429,
    )
    assert kind == FailureKind.DAILY_QUOTA
    assert is_non_retryable(kind)


def test_tpm_is_retryable() -> None:
    kind = classify_message(
        "Rate limit reached for tokens per minute (TPM): Limit 8000",
        status=429,
    )
    assert kind == FailureKind.RATE_LIMIT_TPM
    assert not is_non_retryable(kind)


def test_context_overflow_fatal() -> None:
    kind = classify_message(
        "This model's maximum context length is 8192 tokens",
        status=400,
    )
    assert kind == FailureKind.CONTEXT_OVERFLOW
    assert is_non_retryable(kind)


def test_auth_fatal() -> None:
    kind = classify_message("Invalid API key", status=401)
    assert kind == FailureKind.AUTH_CONFIG
    assert is_non_retryable(kind)
