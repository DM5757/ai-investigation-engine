"""JSON Lines parser (one ParsedDocument per record)."""

from __future__ import annotations

import json
from typing import Any

from app.errors import ParseError
from app.ingestion.metadata import apply_common_metadata, coalesce_str
from app.ingestion.normalize import normalize_text
from app.ingestion.parsers.base import (
    ParsedDocument,
    decode_bytes,
    single_span,
    title_from_filename,
)

_TEXT_KEYS = ("text", "content", "body", "passage")
_TITLE_KEYS = ("title", "name", "headline")
_AUTHOR_KEYS = ("author", "authors", "byline")
_DATE_KEYS = ("date", "doc_date", "published", "published_at", "created_at")


class JsonlParser:
    """Parse JSONL. Prefer ``parse_records`` for multi-document input."""

    def parse_bytes(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        records = self.parse_records(data, filename=filename)
        if len(records) == 1:
            return records[0]
        raise ParseError(
            "JSONL contains multiple records; use parse_records() for multi-document input"
        )

    def parse_records(
        self,
        data: bytes,
        *,
        filename: str | None = None,
    ) -> list[ParsedDocument]:
        raw = decode_bytes(data)
        if not raw.strip():
            raise ParseError("JSONL document is empty")

        docs: list[ParsedDocument] = []
        for line_no, line in enumerate(raw.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ParseError(f"Invalid JSON on line {line_no}: {exc}") from exc
            if not isinstance(obj, dict):
                raise ParseError(f"JSONL line {line_no} must be an object")
            docs.append(_record_to_doc(obj, filename=filename, line_no=line_no))

        if not docs:
            raise ParseError("JSONL document is empty")
        return docs


def _record_to_doc(
    obj: dict[str, Any],
    *,
    filename: str | None,
    line_no: int,
) -> ParsedDocument:
    text_raw = _first_value(obj, _TEXT_KEYS)
    if text_raw is None:
        raise ParseError(f"JSONL line {line_no} missing text field")
    text = normalize_text(str(text_raw))
    if not text:
        raise ParseError(f"JSONL line {line_no} has empty text")

    title = coalesce_str(
        _first_value(obj, _TITLE_KEYS),
        f"{title_from_filename(filename)}#{line_no}",
    ) or f"record-{line_no}"
    author = coalesce_str(_first_value(obj, _AUTHOR_KEYS))
    date_raw = _first_value(obj, _DATE_KEYS)
    metadata = apply_common_metadata(
        {},
        title=title,
        author=str(author) if author is not None else None,
        doc_date_raw=date_raw,
        source_type="jsonl",
        extra={"line_no": line_no},
    )
    # Preserve extra non-core keys for downstream use.
    for key, value in obj.items():
        if key not in metadata and key not in _TEXT_KEYS:
            metadata.setdefault(f"field_{key}", value)
    return ParsedDocument(
        text=text,
        title=title,
        metadata=metadata,
        spans=single_span(text),
    )


def _first_value(obj: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None
