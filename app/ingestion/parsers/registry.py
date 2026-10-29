"""Parser registry keyed by extension / content-type."""

from __future__ import annotations

from app.errors import UnsupportedFormat
from app.ingestion.parsers.base import ParsedDocument, Parser
from app.ingestion.parsers.csv_parser import CsvParser
from app.ingestion.parsers.docx_file import DocxParser
from app.ingestion.parsers.html import HtmlParser
from app.ingestion.parsers.jsonl import JsonlParser
from app.ingestion.parsers.md import MdParser
from app.ingestion.parsers.pdf import PdfParser
from app.ingestion.parsers.txt import TxtParser

_EXTENSION_MAP: dict[str, Parser] = {
    ".txt": TxtParser(),
    ".md": MdParser(),
    ".markdown": MdParser(),
    ".pdf": PdfParser(),
    ".docx": DocxParser(),
    ".html": HtmlParser(),
    ".htm": HtmlParser(),
    ".jsonl": JsonlParser(),
    ".csv": CsvParser(),
}

_CONTENT_TYPE_MAP: dict[str, Parser] = {
    "text/plain": TxtParser(),
    "text/markdown": MdParser(),
    "application/pdf": PdfParser(),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxParser(),
    "text/html": HtmlParser(),
    "application/jsonl": JsonlParser(),
    "application/x-ndjson": JsonlParser(),
    "text/csv": CsvParser(),
}


def get_parser(
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> Parser:
    """Resolve a parser from filename extension and/or content-type."""
    if content_type:
        ctype = content_type.split(";", 1)[0].strip().lower()
        parser = _CONTENT_TYPE_MAP.get(ctype)
        if parser is not None:
            return parser
    if filename:
        lower = filename.lower()
        for ext, parser in _EXTENSION_MAP.items():
            if lower.endswith(ext):
                return parser
    raise UnsupportedFormat(
        f"Unsupported format for filename={filename!r} content_type={content_type!r}"
    )


def parse_bytes(
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> ParsedDocument:
    """Parse bytes using the registry-resolved parser."""
    parser = get_parser(filename=filename, content_type=content_type)
    return parser.parse_bytes(data, filename=filename)


def parse_document(filename: str, data: bytes) -> ParsedDocument:
    """Public API: parse a single document by filename + bytes."""
    return parse_bytes(data, filename=filename)


def parse_jsonl_records(
    data: bytes,
    *,
    filename: str | None = None,
) -> list[ParsedDocument]:
    """Parse JSONL into one ParsedDocument per non-empty line."""
    return JsonlParser().parse_records(data, filename=filename)
