"""Classify LLM provider failures for retry vs fail-fast decisions."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class FailureKind(StrEnum):
    """Sanitized failure categories safe to expose in traces/API text."""

    RATE_LIMIT_RPM = "rate_limit_rpm"
    RATE_LIMIT_TPM = "rate_limit_tpm"
    DAILY_QUOTA = "daily_quota"
    CONTEXT_OVERFLOW = "context_overflow"
    AUTH_CONFIG = "auth_config"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER_ERROR = "server_error"
    BAD_REQUEST = "bad_request"
    UNKNOWN = "unknown"


# Daily / billing exhaustion — do not retry; failover once then fail-fast.
_DAILY_MARKERS = (
    "per day",
    "per-day",
    "requests per day",
    "tokens per day",
    "daily quota",
    "quota exceeded",
    "exceeded your current quota",
    "insufficient_quota",
    "insufficient quota",
    "generate_content_free_tier",
    "generaterequestsperday",
    "tokensperday",
    "requestsperday",
)

_TPM_MARKERS = (
    "tokens per minute",
    "token per minute",
    "tpm",
    "tokens/minute",
    "rate_limit_tokens",
)

_RPM_MARKERS = (
    "requests per minute",
    "request per minute",
    "rpm",
    "requests/minute",
    "rate_limit_requests",
)

_CONTEXT_MARKERS = (
    "context_length",
    "context length",
    "maximum context",
    "max context",
    "too many tokens",
    "token limit",
    "maximum number of tokens",
    "prompt is too long",
    "payload too large",
    "request too large",
    "content_too_large",
    "input token count",
)


def sanitize_provider_error(message: str, *, limit: int = 180) -> str:
    """Strip likely secrets while keeping a short diagnostic fragment."""
    text = " ".join(str(message).split())
    lowered = text.lower()
    for marker in ("bearer ", "api_key", "api-key", "key="):
        idx = lowered.find(marker)
        if idx >= 0:
            text = text[:idx] + "[redacted]"
            break
    return text[:limit]


def classify_message(message: str, *, status: int | None = None) -> FailureKind:
    """Map provider error text / HTTP status to a FailureKind."""
    lower = str(message).lower()
    if status in (401, 403):
        return FailureKind.AUTH_CONFIG
    if any(m in lower for m in _CONTEXT_MARKERS):
        return FailureKind.CONTEXT_OVERFLOW
    if status == 413:
        return FailureKind.CONTEXT_OVERFLOW
    if any(m in lower for m in _DAILY_MARKERS):
        # Prefer daily over TPM/RPM when both phrases appear.
        return FailureKind.DAILY_QUOTA
    if status == 429 or "rate limit" in lower or "rate_limit" in lower:
        if any(m in lower for m in _TPM_MARKERS):
            return FailureKind.RATE_LIMIT_TPM
        if any(m in lower for m in _RPM_MARKERS):
            return FailureKind.RATE_LIMIT_RPM
        # Unknown 429: treat as short-term rate limit (retryable with backoff).
        return FailureKind.RATE_LIMIT_RPM
    if status is not None and status >= 500:
        return FailureKind.SERVER_ERROR
    if status == 400:
        return FailureKind.BAD_REQUEST
    if "timeout" in lower:
        return FailureKind.TIMEOUT
    if "connection" in lower or "network" in lower:
        return FailureKind.NETWORK
    return FailureKind.UNKNOWN


def is_non_retryable(kind: FailureKind) -> bool:
    """True when further attempts on the same request cannot succeed."""
    return kind in {
        FailureKind.DAILY_QUOTA,
        FailureKind.CONTEXT_OVERFLOW,
        FailureKind.AUTH_CONFIG,
        FailureKind.BAD_REQUEST,
    }


def header_retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    raw = None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        raw = None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


__all__ = [
    "FailureKind",
    "classify_message",
    "header_retry_after",
    "is_non_retryable",
    "sanitize_provider_error",
]
