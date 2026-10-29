"""Document ingestion: parsing, normalization, and chunking."""

from app.ingestion.chunking.base import Chunk, Chunker
from app.ingestion.chunking.registry import get_chunker
from app.ingestion.normalize import normalize_text
from app.ingestion.parsers.base import ParsedDocument, Parser, Span
from app.ingestion.parsers.registry import get_parser, parse_bytes, parse_document

__all__ = [
    "Chunk",
    "Chunker",
    "ParsedDocument",
    "Parser",
    "Span",
    "get_chunker",
    "get_parser",
    "normalize_text",
    "parse_bytes",
    "parse_document",
]
