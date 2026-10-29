"""Shared metadata extraction helpers for parsers."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

_ISO_DATE_RE = re.compile(
    r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?:[Tt ].*)?\b",
)
_SLASH_DATE_RE = re.compile(
    r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})\b",
)


def coalesce_str(*values: object | None) -> str | None:
    """Return the first non-empty string among values."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def parse_doc_date(raw: object | None) -> tuple[str | None, str | None]:
    """Parse a date-like value into (ISO date string, source label).

    Returns ``(None, None)`` when parsing fails.
    """
    if raw is None:
        return None, None
    if isinstance(raw, datetime):
        return raw.date().isoformat(), "datetime"
    if isinstance(raw, date):
        return raw.isoformat(), "date"
    text = str(raw).strip()
    if not text:
        return None, None
    for parser in (_try_iso, _try_slash, _try_fromisoformat):
        result = parser(text)
        if result is not None:
            return result
    return None, None


def _try_iso(text: str) -> tuple[str, str] | None:
    match = _ISO_DATE_RE.search(text)
    if not match:
        return None
    try:
        parsed = date(int(match["y"]), int(match["m"]), int(match["d"]))
    except ValueError:
        return None
    return parsed.isoformat(), "iso_regex"


def _try_slash(text: str) -> tuple[str, str] | None:
    match = _SLASH_DATE_RE.search(text)
    if not match:
        return None
    try:
        parsed = date(int(match["y"]), int(match["m"]), int(match["d"]))
    except ValueError:
        return None
    return parsed.isoformat(), "slash_regex"


def _try_fromisoformat(text: str) -> tuple[str, str] | None:
    cleaned = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    return parsed.date().isoformat(), "fromisoformat"


def apply_common_metadata(
    metadata: dict[str, Any],
    *,
    title: str | None = None,
    author: str | None = None,
    doc_date_raw: object | None = None,
    source_type: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge standard metadata fields into a new dict."""
    out: dict[str, Any] = dict(metadata)
    out["source_type"] = source_type
    if author:
        out["author"] = author
    if title:
        out["title"] = title
    doc_date, doc_date_source = parse_doc_date(doc_date_raw)
    if doc_date:
        out["doc_date"] = doc_date
        out["doc_date_source"] = doc_date_source
    if extra:
        out.update(extra)
    return out
