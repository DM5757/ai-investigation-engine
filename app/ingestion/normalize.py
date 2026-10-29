"""Text normalization for ingestion."""

from __future__ import annotations

import re
import unicodedata

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[^\S\n]{2,}")
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")


def normalize_text(text: str) -> str:
    """Normalize Unicode, newlines, and redundant whitespace.

    Preserves paragraph breaks (blank lines) while collapsing runs of spaces
    and limiting consecutive newlines to two.
    """
    if not text:
        return ""
    out = text.replace("\ufeff", "")
    out = unicodedata.normalize("NFC", out)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = _CTRL_RE.sub("", out)
    out = _TRAILING_WS_RE.sub("\n", out)
    out = _MULTI_SPACE_RE.sub(" ", out)
    out = _MULTI_NL_RE.sub("\n\n", out)
    return out.strip()
