"""Optional in-memory LLM response cache; Protocol ready for Postgres later."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMCache(Protocol):
    """Cache keyed by a stable hash of request parameters."""

    def get(self, key: str) -> dict[str, Any] | None:
        """Return cached payload or None."""

    def set(self, key: str, value: dict[str, Any], *, ttl_s: float | None = None) -> None:
        """Store payload with optional TTL."""


def cache_key(payload: dict[str, Any]) -> str:
    """Stable SHA-256 key for a chat request payload."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class _Entry:
    value: dict[str, Any]
    expires_at: float | None


class InMemoryLLMCache:
    """Process-local TTL cache (not shared across workers)."""

    def __init__(self, *, default_ttl_s: float = 600.0) -> None:
        self.default_ttl_s = default_ttl_s
        self._store: dict[str, _Entry] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at is not None and time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        return dict(entry.value)

    def set(self, key: str, value: dict[str, Any], *, ttl_s: float | None = None) -> None:
        ttl = self.default_ttl_s if ttl_s is None else ttl_s
        expires = None if ttl <= 0 else time.monotonic() + ttl
        self._store[key] = _Entry(value=dict(value), expires_at=expires)
