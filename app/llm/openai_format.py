"""OpenAI chat payload helpers shared by the gateway."""

from __future__ import annotations

import json
from typing import Any

from openai import APIStatusError

from app.llm.retry import FatalLLMError, RetryableLLMError
from app.llm.types import ChatMessage, ToolCall


def messages_to_openai(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        item: dict[str, Any] = {"role": msg.role}
        if msg.content is not None:
            item["content"] = msg.content
        if msg.name:
            item["name"] = msg.name
        if msg.tool_call_id:
            item["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            serialized: list[dict[str, Any]] = []
            for tc in msg.tool_calls:
                entry: dict[str, Any] = {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=True),
                    },
                }
                if tc.provider_extra:
                    # Gemini OpenAI-compat requires thought_signature on subsequent turns.
                    entry["extra_content"] = tc.provider_extra
                serialized.append(entry)
            item["tool_calls"] = serialized
        out.append(item)
    return out


def parse_tool_calls(raw: Any) -> list[ToolCall]:
    if not raw:
        return []
    out: list[ToolCall] = []
    for item in raw:
        fn = getattr(item, "function", None) or (
            item.get("function", {}) if isinstance(item, dict) else {}
        )
        name = getattr(fn, "name", None) or (fn.get("name", "") if isinstance(fn, dict) else "")
        args_raw = getattr(fn, "arguments", None) or (
            fn.get("arguments", "{}") if isinstance(fn, dict) else "{}"
        )
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        call_id = getattr(item, "id", None) or (
            item.get("id", name) if isinstance(item, dict) else name
        )
        extra = getattr(item, "extra_content", None)
        if extra is None and isinstance(item, dict):
            extra = item.get("extra_content")
        provider_extra: dict[str, Any] = {}
        if isinstance(extra, dict):
            provider_extra = dict(extra)
        out.append(
            ToolCall(
                id=str(call_id),
                name=str(name),
                arguments=dict(args),
                provider_extra=provider_extra,
            )
        )
    return out


def classify_status_error(exc: APIStatusError, *, provider: str = "") -> Exception:
    from app.llm.failure import (
        FailureKind,
        classify_message,
        header_retry_after,
        is_non_retryable,
        sanitize_provider_error,
    )

    status = int(getattr(exc, "status_code", None) or 0)
    headers = getattr(exc, "headers", None) or {}
    retry_after = header_retry_after(headers)
    msg = sanitize_provider_error(str(exc))
    kind = classify_message(msg, status=status)

    # Gemini sometimes emits 400 for transient tool-schema / signature issues.
    if status == 400:
        lower = msg.lower()
        if "thought_signature" in lower or "extra_content" in lower:
            return RetryableLLMError(
                f"retryable LLM status {status}: {msg}",
                retry_after_s=retry_after,
                kind=FailureKind.BAD_REQUEST,
                provider=provider,
            )

    if is_non_retryable(kind) or status in (401, 403, 413):
        return FatalLLMError(
            f"fatal LLM status {status}: {msg}",
            kind=kind if kind != FailureKind.UNKNOWN else (
                FailureKind.AUTH_CONFIG if status in (401, 403) else FailureKind.BAD_REQUEST
            ),
            provider=provider,
        )
    if status == 429 or status >= 500 or kind in {
        FailureKind.RATE_LIMIT_RPM,
        FailureKind.RATE_LIMIT_TPM,
        FailureKind.SERVER_ERROR,
    }:
        return RetryableLLMError(
            f"retryable LLM status {status}: {msg}",
            retry_after_s=retry_after,
            kind=kind if kind != FailureKind.UNKNOWN else (
                FailureKind.SERVER_ERROR if status >= 500 else FailureKind.RATE_LIMIT_RPM
            ),
            provider=provider,
        )
    return FatalLLMError(
        f"LLM status {status}: {msg}",
        kind=kind,
        provider=provider,
    )
