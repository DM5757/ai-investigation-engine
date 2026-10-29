"""Unit tests for document parsers and registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import ParseError, UnsupportedFormat
from app.ingestion.parsers.csv_parser import CsvParser
from app.ingestion.parsers.docx_file import DocxParser
from app.ingestion.parsers.html import HtmlParser
from app.ingestion.parsers.jsonl import JsonlParser
from app.ingestion.parsers.md import MdParser
from app.ingestion.parsers.pdf import PdfParser
from app.ingestion.parsers.registry import get_parser, parse_bytes, parse_jsonl_records
from app.ingestion.parsers.txt import TxtParser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "docs"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_txt_parser() -> None:
    doc = TxtParser().parse_bytes(_load("sample.txt"), filename="sample.txt")
    assert "billing service" in doc.text
    assert doc.title == "sample"
    assert doc.metadata["source_type"] == "txt"
    assert doc.spans
    assert doc.spans[0].start == 0
    assert doc.spans[0].end == len(doc.text)


def test_md_parser_front_matter_and_headings() -> None:
    doc = MdParser().parse_bytes(_load("sample.md"), filename="sample.md")
    assert doc.title == "Incident Report March"
    assert doc.metadata["author"] == "Alex Chen"
    assert doc.metadata["doc_date"] == "2024-03-15"
    assert any(s.heading_path and "Timeline" in s.heading_path for s in doc.spans)


def test_html_parser_meta() -> None:
    doc = HtmlParser().parse_bytes(_load("sample.html"), filename="sample.html")
    assert doc.title == "Change Log"
    assert doc.metadata["author"] == "Ops Team"
    assert doc.metadata["doc_date"] == "2024-03-01"
    assert "payments worker" in doc.text


def test_docx_parser() -> None:
    doc = DocxParser().parse_bytes(_load("sample.docx"), filename="sample.docx")
    assert "ledger reconciler" in doc.text
    assert doc.title == "DOCX Status"
    assert doc.metadata.get("author") == "Doc Author"
    assert doc.metadata["source_type"] == "docx"


def test_pdf_parser() -> None:
    doc = PdfParser().parse_bytes(_load("sample.pdf"), filename="sample.pdf")
    assert "payment outages" in doc.text.lower() or "PDF sample" in doc.text
    assert doc.metadata["page_count"] == 1
    assert doc.metadata["source_type"] == "pdf"
    assert doc.spans and doc.spans[0].page == 1


def test_pdf_empty_rejected() -> None:
    with pytest.raises(ParseError, match="no extractable text"):
        PdfParser().parse_bytes(_load("empty.pdf"), filename="empty.pdf")


def test_jsonl_parse_records() -> None:
    records = JsonlParser().parse_records(_load("sample.jsonl"), filename="sample.jsonl")
    assert len(records) == 2
    assert records[0].title == "Rec A"
    assert records[0].metadata["author"] == "Ann"
    assert records[0].metadata["doc_date"] == "2024-01-01"
    assert "Alpha" in records[0].text
    assert records[1].title == "Rec B"


def test_jsonl_parse_bytes_rejects_multi() -> None:
    with pytest.raises(ParseError, match="multiple records"):
        JsonlParser().parse_bytes(_load("sample.jsonl"), filename="sample.jsonl")


def test_jsonl_single_record_via_parse_bytes() -> None:
    data = b'{"text": "Only one", "title": "Solo"}\n'
    doc = JsonlParser().parse_bytes(data, filename="one.jsonl")
    assert doc.title == "Solo"
    assert doc.text == "Only one"


def test_csv_parser() -> None:
    doc = CsvParser().parse_bytes(_load("sample.csv"), filename="sample.csv")
    assert "payments" in doc.text
    assert doc.metadata["row_count"] == 2
    assert doc.metadata["source_type"] == "csv"


def test_registry_by_extension_and_content_type() -> None:
    assert isinstance(get_parser(filename="x.MD"), MdParser)
    assert isinstance(get_parser(content_type="application/pdf"), PdfParser)
    doc = parse_bytes(_load("sample.txt"), filename="notes.txt")
    assert doc.metadata["source_type"] == "txt"


def test_registry_unsupported() -> None:
    with pytest.raises(UnsupportedFormat):
        get_parser(filename="file.xyz")


def test_empty_txt_rejected() -> None:
    with pytest.raises(ParseError):
        TxtParser().parse_bytes(b"   \n\n", filename="empty.txt")


def test_parse_jsonl_records_helper() -> None:
    docs = parse_jsonl_records(_load("sample.jsonl"), filename="sample.jsonl")
    assert len(docs) == 2
