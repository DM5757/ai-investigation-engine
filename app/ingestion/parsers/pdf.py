"""PDF parser using pypdf (no OCR)."""

from __future__ import annotations

import io
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.errors import ParseError
from app.ingestion.metadata import apply_common_metadata, coalesce_str
from app.ingestion.normalize import normalize_text
from app.ingestion.parsers.base import ParsedDocument, Span, title_from_filename


class PdfParser:
    """Extract text and metadata from digital PDFs; reject empty/encrypted/scanned."""

    def parse_bytes(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        if not data:
            raise ParseError("PDF document is empty")
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
        except PdfReadError as exc:
            raise ParseError(f"Failed to read PDF: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — surface as ParseError
            raise ParseError(f"Failed to read PDF: {exc}") from exc

        if getattr(reader, "is_encrypted", False):
            # Some readers set is_encrypted True even after empty-password decrypt.
            try:
                if reader.decrypt("") == 0:
                    raise ParseError("PDF is encrypted")
            except ParseError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ParseError("PDF is encrypted") from exc

        page_texts: list[tuple[int, str]] = []
        for page_idx, page in enumerate(reader.pages):
            try:
                extracted = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                raise ParseError(f"Failed to extract PDF page {page_idx + 1}: {exc}") from exc
            page_texts.append((page_idx + 1, extracted))

        joined_raw = "\n\n".join(t for _, t in page_texts)
        if not normalize_text(joined_raw):
            raise ParseError("PDF has no extractable text (empty or scanned)")

        parts: list[str] = []
        spans: list[Span] = []
        offset = 0
        for page_no, raw_page in page_texts:
            page_text = normalize_text(raw_page)
            if not page_text:
                continue
            if parts:
                parts.append("\n\n")
                offset += 2
            start = offset
            parts.append(page_text)
            offset += len(page_text)
            spans.append(Span(start=start, end=offset, page=page_no))

        text = "".join(parts)
        if not text:
            raise ParseError("PDF has no extractable text (empty or scanned)")

        info = _safe_metadata(reader)
        title = coalesce_str(info.get("title"), title_from_filename(filename)) or "untitled"
        author = coalesce_str(info.get("author"))
        date_raw = coalesce_str(info.get("creation_date"), info.get("mod_date"))
        metadata = apply_common_metadata(
            {},
            title=title,
            author=author,
            doc_date_raw=date_raw,
            source_type="pdf",
            extra={"page_count": len(reader.pages)},
        )
        return ParsedDocument(text=text, title=title, metadata=metadata, spans=spans)


def _safe_metadata(reader: PdfReader) -> dict[str, Any]:
    meta = getattr(reader, "metadata", None)
    if meta is None:
        return {}
    mapping: dict[str, Any] = {}
    title = getattr(meta, "title", None)
    author = getattr(meta, "author", None)
    creation = getattr(meta, "creation_date", None)
    modified = getattr(meta, "modification_date", None)
    if title:
        mapping["title"] = str(title)
    if author:
        mapping["author"] = str(author)
    if creation:
        mapping["creation_date"] = creation
    if modified:
        mapping["mod_date"] = modified
    return mapping
