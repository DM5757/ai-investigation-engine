"""Investigation trace helpers."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.schemas.evidence import TraceEvent, UsageStats


class TraceRecorder:
    """Append-only list of stage TraceEvents."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def append(
        self,
        stage: str,
        *,
        inputs_summary: str = "",
        outputs_summary: str = "",
        latency_ms: float = 0.0,
        tokens: UsageStats | None = None,
        extra: dict[str, Any] | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            stage=stage,
            inputs_summary=inputs_summary[:500],
            outputs_summary=outputs_summary[:500],
            latency_ms=latency_ms,
            tokens=tokens or UsageStats(),
            extra=extra or {},
        )
        self.events.append(event)
        return event

    @contextmanager
    def stage(self, name: str, *, inputs_summary: str = "") -> Iterator[dict[str, Any]]:
        """Time a stage; caller mutates the returned dict for outputs/tokens."""
        bag: dict[str, Any] = {
            "outputs_summary": "",
            "tokens": UsageStats(),
            "extra": {},
        }
        started = time.perf_counter()
        try:
            yield bag
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.append(
                name,
                inputs_summary=inputs_summary,
                outputs_summary=str(bag.get("outputs_summary", "")),
                latency_ms=elapsed_ms,
                tokens=bag.get("tokens") or UsageStats(),
                extra=dict(bag.get("extra") or {}),
            )
