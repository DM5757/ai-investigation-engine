"""Unit tests for token-bucket rate limiter."""

from __future__ import annotations

from app.api.ratelimit import DailyCounter, TokenBucketLimiter


def test_token_bucket_allows_burst_then_blocks() -> None:
    lim = TokenBucketLimiter(rate_per_min=60, burst=2)
    assert lim.allow("a") is True
    assert lim.allow("a") is True
    assert lim.allow("a") is False


def test_token_bucket_independent_keys() -> None:
    lim = TokenBucketLimiter(rate_per_min=60, burst=1)
    assert lim.allow("x") is True
    assert lim.allow("y") is True
    assert lim.allow("x") is False


def test_daily_counter_cap() -> None:
    c = DailyCounter(cap=2)
    assert c.try_increment() is True
    assert c.try_increment() is True
    assert c.try_increment() is False
    assert c.remaining() == 0


def test_daily_counter_disabled() -> None:
    c = DailyCounter(cap=0)
    assert c.try_increment(100) is True
    assert c.remaining() is None
