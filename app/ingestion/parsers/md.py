"""Markdown parser with optional YAML front matter."""

from __future__ import annotations

import re
from typing import Any

import yaml

from app.errors import ParseError
from app.ingestion.metadata import apply_common_metadata, coalesce_str
from app.ingestion.normalize import normalize_text
from app.ingestion.parsers.base import (
    ParsedDocument,
    Span,
    decode_bytes,
    title_from_filename,
)

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


class MdParser:
    """Parse Markdown; extract title/author/date from front matter or H1."""

    def parse_bytes(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        raw = decode_bytes(data)
        body, front = _split_front_matter(raw)
        text = normalize_text(body)
        if not text:
            raise ParseError("Markdown document is empty")

        h1 = _first_heading(text, level=1)
        title = coalesce_str(
            front.get("title"),
            h1,
            title_from_filename(filename),
        ) or "untitled"
        author = coalesce_str(front.get("author"), front.get("authors"))
        date_raw = coalesce_str(front.get("date"), front.get("doc_date"))
        metadata = apply_common_metadata(
            {},
            title=title,
            author=author,
            doc_date_raw=date_raw,
            source_type="md",
            extra={"has_front_matter": bool(front)},
        )
        spans = _heading_spans(text)
        return ParsedDocument(text=text, title=title, metadata=metadata, spans=spans)


def _split_front_matter(raw: str) -> tuple[str, dict[str, Any]]:
    match = _FRONT_MATTER_RE.match(raw)
    if not match:
        return raw, {}
    try:
        loaded = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ParseError(f"Invalid Markdown front matter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ParseError("Markdown front matter must be a mapping")
    return raw[match.end() :], {str(k): v for k, v in loaded.items()}


def _first_heading(text: str, *, level: int) -> str | None:
    for match in _HEADING_RE.finditer(text):
        if len(match.group(1)) == level:
            return match.group(2).strip()
    return None


def _heading_spans(text: str) -> list[Span]:
    """Build spans segmented by ATX headings with heading_path breadcrumbs."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [Span(0, len(text))] if text else []

    stack: list[str] = []
    spans: list[Span] = []
    # Leading prose before first heading
    if matches[0].start() > 0:
        spans.append(Span(0, matches[0].start(), heading_path=None))

    for idx, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        stack = stack[: level - 1]
        stack.append(heading)
        path = " > ".join(stack)
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        spans.append(Span(start, end, heading_path=path))
    return spans
