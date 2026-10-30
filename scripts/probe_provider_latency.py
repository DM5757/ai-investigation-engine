"""Low-volume provider latency probe (does not run a full investigation)."""

from __future__ import annotations

import json
import time

from openai import APIStatusError, OpenAI

from app.config import get_settings
from app.llm.failure import classify_message, sanitize_provider_error


def _probe(name: str, key: str, base: str, model: str) -> dict[str, object]:
    client = OpenAI(api_key=key, base_url=base, timeout=60.0)
    t0 = time.perf_counter()
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Reply with JSON only."},
                {
                    "role": "user",
                    "content": (
                        'Return {"ok": true, "label": "probe"} as JSON. '
                        "Do not add other keys."
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=32,
        )
        ms = (time.perf_counter() - t0) * 1000.0
        usage = completion.usage
        content = completion.choices[0].message.content or ""
        return {
            "provider": name,
            "ok": True,
            "latency_ms": round(ms, 1),
            "tokens": getattr(usage, "total_tokens", None),
            "content_len": len(content),
        }
    except APIStatusError as exc:
        ms = (time.perf_counter() - t0) * 1000.0
        msg = sanitize_provider_error(str(exc))
        return {
            "provider": name,
            "ok": False,
            "latency_ms": round(ms, 1),
            "status": exc.status_code,
            "kind": classify_message(msg, status=exc.status_code).value,
            "detail": msg,
        }
    except Exception as exc:  # noqa: BLE001 — probe surface
        ms = (time.perf_counter() - t0) * 1000.0
        return {
            "provider": name,
            "ok": False,
            "latency_ms": round(ms, 1),
            "kind": type(exc).__name__,
            "detail": sanitize_provider_error(str(exc)),
        }


def main() -> None:
    settings = get_settings()
    rows: list[dict[str, object]] = []
    if settings.groq_api_key:
        rows.append(
            _probe(
                "groq",
                settings.groq_api_key.get_secret_value(),
                settings.groq_base_url,
                settings.groq_model,
            )
        )
    if settings.gemini_api_key:
        rows.append(
            _probe(
                "gemini",
                settings.gemini_api_key.get_secret_value(),
                settings.gemini_base_url,
                settings.gemini_model,
            )
        )
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
