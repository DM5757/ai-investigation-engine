"""HTML parser using BeautifulSoup + lxml."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from app.errors import ParseError
from app.ingestion.metadata import apply_common_metadata, coalesce_str
from app.ingestion.normalize import normalize_text
from app.ingestion.parsers.base import ParsedDocument, Span, decode_bytes, title_from_filename

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})


class HtmlParser:
    """Parse HTML into readable text with heading-aware spans."""

    def parse_bytes(self, data: bytes, *, filename: str | None = None) -> ParsedDocument:
        raw = decode_bytes(data)
        if not raw.strip():
            raise ParseError("HTML document is empty")
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(_SKIP_TAGS):
            tag.decompose()

        title = coalesce_str(
            _meta_content(soup, "og:title"),
            soup.title.string if soup.title else None,
            _first_heading(soup),
            title_from_filename(filename),
        ) or "untitled"
        author = coalesce_str(
            _meta_content(soup, "author"),
            _meta_name(soup, "author"),
        )
        date_raw = coalesce_str(
            _meta_content(soup, "article:published_time"),
            _meta_name(soup, "date"),
            _meta_name(soup, "pubdate"),
        )

        body = soup.body if soup.body is not None else soup
        text, spans = _extract_blocks(body)
        text = normalize_text(text)
        if not text:
            raise ParseError("HTML document has no extractable text")
        # After normalize, remap to a single covering span if needed.
        if len(spans) != 1 or spans[0].end != len(text):
            spans = [Span(0, len(text), heading_path=spans[0].heading_path if spans else None)]

        metadata = apply_common_metadata(
            {},
            title=title,
            author=author,
            doc_date_raw=date_raw,
            source_type="html",
        )
        return ParsedDocument(text=text, title=title, metadata=metadata, spans=spans)


def _meta_content(soup: BeautifulSoup, property_name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": property_name})
    if isinstance(tag, Tag) and tag.get("content"):
        return str(tag["content"])
    return None


def _meta_name(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"name": name})
    if isinstance(tag, Tag) and tag.get("content"):
        return str(tag["content"])
    return None


def _first_heading(soup: BeautifulSoup) -> str | None:
    for level in range(1, 7):
        tag = soup.find(f"h{level}")
        if tag is not None:
            text = tag.get_text(" ", strip=True)
            if text:
                return text
    return None


def _extract_blocks(root: Tag | BeautifulSoup) -> tuple[str, list[Span]]:
    """Walk top-level block-ish children; fall back to full get_text."""
    candidates = root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre"])
    if not candidates:
        text = root.get_text("\n", strip=True)
        if not text:
            return "", []
        return text, [Span(0, len(text))]

    parts: list[str] = []
    spans: list[Span] = []
    stack: list[str] = []
    offset = 0
    for node in candidates:
        if not isinstance(node, Tag):
            continue
        name = (node.name or "").lower()
        block = node.get_text(" ", strip=True)
        if not block:
            continue
        path: str | None
        if name.startswith("h") and len(name) == 2 and name[1].isdigit():
            level = int(name[1])
            stack = stack[: level - 1]
            stack.append(block)
            path = " > ".join(stack)
        else:
            path = " > ".join(stack) if stack else None
        if parts:
            parts.append("\n\n")
            offset += 2
        start = offset
        parts.append(block)
        offset += len(block)
        spans.append(Span(start=start, end=offset, heading_path=path))
    return "".join(parts), spans
