"""Tests for text normalization."""

from __future__ import annotations

from app.ingestion.normalize import normalize_text


def test_normalize_collapses_spaces_and_newlines() -> None:
    raw = "Hello,   world.\r\n\r\n\r\nNext   paragraph.\t\t"
    assert normalize_text(raw) == "Hello, world.\n\nNext paragraph."


def test_normalize_strips_bom_and_control_chars() -> None:
    raw = "\ufeffAlpha\x00Beta\x07"
    assert normalize_text(raw) == "AlphaBeta"


def test_normalize_empty() -> None:
    assert normalize_text("") == ""
    assert normalize_text("   \n\n  ") == ""


def test_normalize_nfc() -> None:
    # Cafe with combining accent vs precomposed
    decomposed = "Cafe\u0301"
    composed = "Café"
    assert normalize_text(decomposed) == composed
