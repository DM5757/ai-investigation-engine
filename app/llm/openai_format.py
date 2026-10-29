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
            item["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=True),
                    },
                }
                for tc in msg.tool_calls
            ]
        out.append(item)
    return out


def parse_tool_calls(raw: Any) -> list[ToolCall]:
    if not raw:
        return []
    out: list[ToolCall] = []
    for item in raw:
        fn = getattr(item, "function", None) or item.get("function", {})
        name = getattr(fn, "name", None) or fn.get("name", "")
        args_raw = getattr(fn, "arguments", None) or fn.get("arguments", "{}")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        call_id = getattr(item, "id", None) or item.get("id", name)
        out.append(ToolCall(id=str(call_id), name=str(name), arguments=dict(args)))
    return out


def classify_status_error(exc: APIStatusError) -> Exception:
    status = getattr(exc, "status_code", None) or 0
    headers = getattr(exc, "headers", None) or {}
    retry_after: float | None = None
    raw_ra = headers.get("retry-after") or headers.get("Retry-After")
    if raw_ra is not None:
        try:
            retry_after = float(raw_ra)
        except (TypeError, ValueError):
            retry_after = None
    msg = str(exc)
    if status in (401, 403, 400):
        return FatalLLMError(f"fatal LLM status {status}: {msg}")
    if status == 429 or status >= 500:
        return RetryableLLMError(
            f"retryable LLM status {status}: {msg}", retry_after_s=retry_after
        )
    return FatalLLMError(f"LLM status {status}: {msg}")
