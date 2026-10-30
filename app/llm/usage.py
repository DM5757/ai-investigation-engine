"""Per-stage usage accounting and call/token budgets."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.errors import BudgetExceeded
from app.schemas.evidence import UsageStats


@dataclass
class UsageTracker:
    """Accumulate token and call counts keyed by investigation stage."""

    by_stage: dict[str, UsageStats] = field(default_factory=dict)
    total: UsageStats = field(default_factory=UsageStats)

    def record(self, stage: str, usage: UsageStats) -> None:
        existing = self.by_stage.get(stage, UsageStats())
        self.by_stage[stage] = existing.add(usage)
        self.total = self.total.add(usage)

    def snapshot(self) -> UsageStats:
        return self.total.model_copy()


@dataclass
class BudgetTracker:
    """Enforce max LLM calls, tokens, and wall-clock budget."""

    max_calls: int = 20
    max_tokens: int = 50_000
    max_wall_clock_s: float = 120.0
    calls_used: int = 0
    tokens_used: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def reset(self) -> None:
        """Clear counters for a new investigation / eval question."""
        self.calls_used = 0
        self.tokens_used = 0
        self.started_at = time.monotonic()

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def remaining_s(self) -> float:
        return max(0.0, self.max_wall_clock_s - self.elapsed_s())

    def check(self) -> None:
        elapsed = self.elapsed_s()
        if self.calls_used >= self.max_calls:
            raise BudgetExceeded(f"max LLM calls exceeded ({self.max_calls})")
        if self.tokens_used >= self.max_tokens:
            raise BudgetExceeded(f"max tokens exceeded ({self.max_tokens})")
        if elapsed >= self.max_wall_clock_s:
            raise BudgetExceeded(f"wall clock budget exceeded ({self.max_wall_clock_s}s)")

    def consume(self, usage: UsageStats) -> None:
        """Record usage for a completed call. ``check()`` gates the *next* call."""
        self.check()
        self.calls_used += max(1, usage.calls or 1)
        self.tokens_used += usage.total_tokens
        elapsed = self.elapsed_s()
        if self.tokens_used > self.max_tokens:
            raise BudgetExceeded(f"max tokens exceeded ({self.max_tokens})")
        if elapsed >= self.max_wall_clock_s:
            raise BudgetExceeded(f"wall clock budget exceeded ({self.max_wall_clock_s}s)")
