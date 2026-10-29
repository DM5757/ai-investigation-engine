"""Plain-text parser."""

from __future__ import annotations

from app.errors import ParseError
from app.ingestion.metadata import apply_common_metadata
from app.ingestion.normalize import normalize_text
from app.ingestion.parsers.base import (
    ParsedDocument,
    decode_bytes,
    single_span,
    title_from_filename,
)


class TxtParser:
    """Parse ``.txt`` files as UTF-8 (or latin-1 fallback) plain text."""

    def parse_bytes(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        raw = decode_bytes(data)
        text = normalize_text(raw)
        if not text:
            raise ParseError("TXT document is empty")
        title = title_from_filename(filename)
        metadata = apply_common_metadata({}, title=title, source_type="txt")
        return ParsedDocument(
            text=text,
            title=title,
            metadata=metadata,
            spans=single_span(text),
        )
