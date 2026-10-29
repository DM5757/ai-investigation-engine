"""JSON repair and LLMOutputInvalid path."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.errors import LLMOutputInvalid
from app.llm.json_repair import parse_model, repair_json


class _Tiny(BaseModel):
    note: str


def test_repair_fenced_json() -> None:
    raw = "Here you go:\n```json\n{\"note\": \"ok\"}\n```"
    assert parse_model(raw, _Tiny).note == "ok"


def test_repair_trailing_comma() -> None:
    repaired = repair_json('{"note": "x",}')
    assert parse_model(repaired, _Tiny).note == "x"


def test_invalid_raises() -> None:
    with pytest.raises(LLMOutputInvalid):
        parse_model("not json at all {{{", _Tiny)
