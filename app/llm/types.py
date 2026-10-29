"""Shared chat message / result types for the LLM gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.schemas.evidence import UsageStats


@dataclass
class ToolCall:
    """One structured tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]
    # Provider-specific extras (e.g. Gemini thought_signature) required on round-trip.
    provider_extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    """OpenAI-style chat message."""

    role: str
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


@dataclass
class ChatResult:
    """Normalized provider response."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: UsageStats = field(default_factory=UsageStats)
    provider: str = ""
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMClient(Protocol):
    """Minimal chat interface used by the investigation engine."""

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
        """Send a chat completion request."""
