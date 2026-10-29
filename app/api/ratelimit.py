"""Per-IP token-bucket rate limiting and optional daily LLM call counter."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from fastapi import Request

from app.errors import AppError


class RateLimited(AppError):
    """Too many requests from this client."""

    code = "rate_limited"
    http_status = 429


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


@dataclass
class TokenBucketLimiter:
    """In-process per-key token bucket."""

    rate_per_min: float
    burst: float
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        refill_per_s = self.rate_per_min / 60.0
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._buckets[key] = _Bucket(tokens=self.burst - 1.0, updated_at=now)
                return True
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(self.burst, bucket.tokens + elapsed * refill_per_s)
            bucket.updated_at = now
            if bucket.tokens < 1.0:
                return False
            bucket.tokens -= 1.0
            return True


@dataclass
class DailyCounter:
    """Global (process-wide) daily counter for LLM calls."""

    cap: int
    count: int = 0
    day_key: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def try_increment(self, n: int = 1) -> bool:
        if self.cap <= 0:
            return True
        with self._lock:
            today = self._today()
            if self.day_key != today:
                self.day_key = today
                self.count = 0
            if self.count + n > self.cap:
                return False
            self.count += n
            return True

    def remaining(self) -> int | None:
        if self.cap <= 0:
            return None
        with self._lock:
            today = self._today()
            if self.day_key != today:
                return self.cap
            return max(0, self.cap - self.count)


def client_ip(request: Request) -> str:
    """Best-effort client IP (honours first X-Forwarded-For hop)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client is not None:
        return request.client.host
    return "unknown"


def enforce_query_rate_limit(request: Request) -> None:
    """Consume one token from the process query limiter; raise if exhausted."""
    limiter = getattr(request.app.state, "query_limiter", None)
    if limiter is None:
        return
    if not limiter.allow(client_ip(request)):
        raise RateLimited("query rate limit exceeded; try again shortly")
