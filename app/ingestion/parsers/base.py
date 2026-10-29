"""Parser protocol and shared document types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Span:
    """Character span in the extracted document text."""

    start: int
    end: int
    page: int | None = None
    heading_path: str | None = None


@dataclass(slots=True)
class ParsedDocument:
    """Normalized parse result for a single logical document."""

    text: str
    title: str
    metadata: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)


@runtime_checkable
class Parser(Protocol):
    """Byte-oriented document parser."""

    def parse_bytes(
        self,
        data: bytes,
        *,
        filename: str | None = None,
    ) -> ParsedDocument:
        """Parse raw bytes into a ParsedDocument."""
        ...


def decode_bytes(data: bytes) -> str:
    """Decode bytes as UTF-8 with BOM/latin-1 fallbacks."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def title_from_filename(filename: str | None, fallback: str = "untitled") -> str:
    """Derive a display title from a filename stem."""
    if not filename:
        return fallback
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    name = name.strip()
    return name or fallback


def single_span(
    text: str,
    *,
    page: int | None = None,
    heading_path: str | None = None,
) -> list[Span]:
    """Return a single span covering the whole text, or empty if blank."""
    if not text:
        return []
    return [Span(start=0, end=len(text), page=page, heading_path=heading_path)]
