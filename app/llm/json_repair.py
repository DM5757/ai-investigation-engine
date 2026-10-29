"""Best-effort JSON extraction / repair for LLM structured outputs."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.errors import LLMOutputInvalid

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json_text(raw: str) -> str:
    """Strip markdown fences and leading/trailing noise around a JSON value."""
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj < 0 and start_arr < 0:
        return text
    if start_obj < 0:
        start = start_arr
        end_char = "]"
    elif start_arr < 0:
        start = start_obj
        end_char = "}"
    else:
        start = min(start_obj, start_arr)
        end_char = "}" if start == start_obj else "]"
    end = text.rfind(end_char)
    if end > start:
        return text[start : end + 1]
    return text[start:]


def repair_json(raw: str) -> str:
    """Apply light repairs: fences, trailing commas, single quotes."""
    text = extract_json_text(raw)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    if text.count("'") > text.count('"') and '"' not in text[:40]:
        text = text.replace("'", '"')
    return text


def parse_model(raw: str, model: type[T]) -> T:
    """Validate JSON into ``model`` with one repair attempt."""
    attempts = [raw.strip(), repair_json(raw)]
    errors: list[str] = []
    for candidate in attempts:
        try:
            data = json.loads(candidate)
            return model.model_validate(data)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            errors.append(str(exc))
    raise LLMOutputInvalid(
        f"invalid LLM JSON for {model.__name__}: {'; '.join(errors)[:400]}"
    )
