"""OpenAI-compatible LLM gateway with Groq → Gemini fallback."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.config import Settings, get_settings
from app.errors import BudgetExceeded, LLMUnavailable
from app.llm.cache import InMemoryLLMCache, LLMCache, cache_key
from app.llm.openai_format import classify_status_error, messages_to_openai, parse_tool_calls
from app.llm.retry import FatalLLMError, RetryableLLMError, RetryPolicy, with_retries
from app.llm.types import ChatMessage, ChatResult, LLMClient, ToolCall
from app.llm.usage import BudgetTracker, UsageTracker
from app.schemas.evidence import UsageStats

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class OpenAICompatibleClient:
    """Single-provider OpenAI SDK client (Groq, Gemini OpenAI endpoint, etc.)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        name: str,
        timeout_s: float = 30.0,
    ) -> None:
        self.name = name
        self.model = model
        self.timeout_s = timeout_s
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s)

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
        _ = stage
        if tools and response_format:
            raise FatalLLMError("do not combine tools with response_format in one call")
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages_to_openai(messages),
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
        if response_format:
            kwargs["response_format"] = response_format
        try:
            completion = self._client.chat.completions.create(**kwargs)
        except APITimeoutError as exc:
            raise RetryableLLMError(f"timeout: {exc}") from exc
        except APIConnectionError as exc:
            raise RetryableLLMError(f"connection: {exc}") from exc
        except APIStatusError as exc:
            raise classify_status_error(exc) from exc
        choice = completion.choices[0].message
        usage_raw = completion.usage
        usage = UsageStats(
            prompt_tokens=int(getattr(usage_raw, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage_raw, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage_raw, "total_tokens", 0) or 0),
            calls=1,
        )
        return ChatResult(
            content=choice.content,
            tool_calls=parse_tool_calls(choice.tool_calls),
            usage=usage,
            provider=self.name,
            model=self.model,
        )


class LLMGateway:
    """Chain of providers with retries, budget, optional cache, and usage tracking."""

    def __init__(
        self,
        providers: Sequence[LLMClient],
        *,
        retry_policy: RetryPolicy | None = None,
        budget: BudgetTracker | None = None,
        usage: UsageTracker | None = None,
        cache: LLMCache | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.providers = list(providers)
        self.retry_policy = retry_policy or RetryPolicy()
        self.budget = budget or BudgetTracker()
        self.usage = usage or UsageTracker()
        self.cache = cache
        self._sleeper = sleeper

    @property
    def available(self) -> bool:
        return bool(self.providers)

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
        if not self.providers:
            raise LLMUnavailable("no LLM providers configured")
        self.budget.check()
        key_payload = {
            "messages": [m.__dict__ for m in messages],
            "tools": tools,
            "response_format": response_format,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stage": stage,
        }
        cached = self._cache_get(key_payload)
        if cached is not None:
            return cached

        errors: list[str] = []
        for provider in self.providers:
            try:
                result = self._chat_one(
                    provider,
                    messages,
                    tools=tools,
                    response_format=response_format,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stage=stage,
                )
                self.usage.record(stage or "unknown", result.usage)
                self.budget.consume(result.usage)
                self._cache_set(key_payload, result)
                return result
            except BudgetExceeded:
                raise
            except FatalLLMError as exc:
                errors.append(f"{getattr(provider, 'name', provider)}:fatal:{exc}")
                logger.warning("LLM fatal on provider: %s", exc)
            except RetryableLLMError as exc:
                errors.append(f"{getattr(provider, 'name', provider)}:retry:{exc}")
                logger.warning("LLM retries exhausted: %s", exc)
        raise LLMUnavailable("; ".join(errors) or "all providers failed")

    def _cache_get(self, key_payload: dict[str, Any]) -> ChatResult | None:
        if self.cache is None:
            return None
        hit = self.cache.get(cache_key(key_payload))
        if hit is None:
            return None
        return ChatResult(
            content=hit.get("content"),
            tool_calls=[ToolCall(**tc) for tc in hit.get("tool_calls", [])],
            usage=UsageStats(**hit.get("usage", {"calls": 0})),
            provider=str(hit.get("provider", "cache")),
            model=str(hit.get("model", "")),
        )

    def _cache_set(self, key_payload: dict[str, Any], result: ChatResult) -> None:
        if self.cache is None:
            return
        self.cache.set(
            cache_key(key_payload),
            {
                "content": result.content,
                "tool_calls": [tc.__dict__ for tc in result.tool_calls],
                "usage": result.usage.model_dump(),
                "provider": result.provider,
                "model": result.model,
            },
        )

    def _chat_one(
        self,
        provider: LLMClient,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, Any] | None,
        temperature: float,
        max_tokens: int | None,
        stage: str,
    ) -> ChatResult:
        def _call() -> ChatResult:
            return provider.chat(
                messages,
                tools=tools,
                response_format=response_format,
                temperature=temperature,
                max_tokens=max_tokens,
                stage=stage,
            )

        kwargs: dict[str, Any] = {"policy": self.retry_policy}
        if self._sleeper is not None:
            kwargs["sleeper"] = self._sleeper
        return with_retries(_call, **kwargs)


def build_gateway(settings: Settings | None = None) -> LLMGateway:
    """Construct gateway from settings; empty providers → degraded mode."""
    cfg = settings or get_settings()
    providers: list[LLMClient] = []
    groq_key = cfg.groq_api_key.get_secret_value() if cfg.groq_api_key else None
    if groq_key:
        providers.append(
            OpenAICompatibleClient(
                api_key=groq_key,
                base_url=cfg.groq_base_url,
                model=cfg.groq_model,
                name="groq",
                timeout_s=cfg.llm_timeout_s,
            )
        )
    gemini_key = cfg.gemini_api_key.get_secret_value() if cfg.gemini_api_key else None
    if gemini_key:
        providers.append(
            OpenAICompatibleClient(
                api_key=gemini_key,
                base_url=cfg.gemini_base_url,
                model=cfg.gemini_model,
                name="gemini",
                timeout_s=cfg.llm_timeout_s,
            )
        )
    return LLMGateway(
        providers,
        retry_policy=RetryPolicy(
            max_attempts=cfg.llm_max_retries,
            base_delay_s=cfg.llm_retry_base_s,
            max_delay_s=cfg.llm_retry_max_s,
        ),
        budget=BudgetTracker(
            max_calls=cfg.llm_budget_max_calls,
            max_tokens=cfg.llm_budget_max_tokens,
            max_wall_clock_s=cfg.llm_budget_wall_clock_s,
        ),
        # Process-local cache reduces repeat free-tier spend within one eval/run.
        cache=InMemoryLLMCache(default_ttl_s=3600.0),
    )


__all__ = [
    "GEMINI_OPENAI_BASE_URL",
    "GROQ_BASE_URL",
    "LLMClient",
    "LLMGateway",
    "OpenAICompatibleClient",
    "build_gateway",
]
