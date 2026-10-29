"""CSV parser (optional format)."""

from __future__ import annotations

import csv
import io

from app.errors import ParseError
from app.ingestion.metadata import apply_common_metadata
from app.ingestion.normalize import normalize_text
from app.ingestion.parsers.base import (
    ParsedDocument,
    decode_bytes,
    single_span,
    title_from_filename,
)


class CsvParser:
    """Parse CSV into a single text document (header + row lines)."""

    def parse_bytes(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        raw = decode_bytes(data)
        if not raw.strip():
            raise ParseError("CSV document is empty")
        reader = csv.reader(io.StringIO(raw))
        rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not rows:
            raise ParseError("CSV document is empty")

        lines: list[str] = []
        header = rows[0]
        lines.append(" | ".join(cell.strip() for cell in header))
        for row in rows[1:]:
            pairs = []
            for idx, cell in enumerate(row):
                key = header[idx].strip() if idx < len(header) else f"col{idx}"
                pairs.append(f"{key}: {cell.strip()}")
            lines.append("; ".join(pairs))

        text = normalize_text("\n".join(lines))
        if not text:
            raise ParseError("CSV document is empty")
        title = title_from_filename(filename)
        metadata = apply_common_metadata(
            {},
            title=title,
            source_type="csv",
            extra={"row_count": max(0, len(rows) - 1), "column_count": len(header)},
        )
        return ParsedDocument(
            text=text,
            title=title,
            metadata=metadata,
            spans=single_span(text),
        )
