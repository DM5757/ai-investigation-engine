"""Deterministic LLM double for unit and integration tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.llm.retry import FatalLLMError, RetryableLLMError
from app.llm.types import ChatMessage, ChatResult, ToolCall
from app.schemas.evidence import UsageStats


@dataclass
class ScriptedResponse:
    """One canned chat outcome (content, tools, or error)."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: UsageStats = field(default_factory=lambda: UsageStats(calls=1, total_tokens=10))
    provider: str = "scripted"
    model: str = "scripted"
    error: Exception | None = None
    delay_s: float = 0.0


class ScriptedLLM:
    """``LLMClient`` that returns pre-scripted responses in order."""

    def __init__(
        self,
        responses: Sequence[ScriptedResponse | Exception] | None = None,
        *,
        name: str = "scripted",
    ) -> None:
        self.name = name
        self._queue: list[ScriptedResponse | Exception] = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def push(self, item: ScriptedResponse | Exception) -> None:
        self._queue.append(item)

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stage: str = "",
    ) -> ChatResult:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "response_format": response_format,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stage": stage,
            }
        )
        if not self._queue:
            raise FatalLLMError("ScriptedLLM queue empty")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if item.error is not None:
            raise item.error
        if item.delay_s > 0:
            import time

            time.sleep(item.delay_s)
        return ChatResult(
            content=item.content,
            tool_calls=list(item.tool_calls),
            usage=item.usage,
            provider=item.provider or self.name,
            model=item.model,
        )


def retryable_429(retry_after_s: float | None = 0.01) -> RetryableLLMError:
    return RetryableLLMError("rate limited", retry_after_s=retry_after_s)
