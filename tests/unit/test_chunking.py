"""Unit and property tests for chunkers and sentence splitting."""

from __future__ import annotations

import pytest

from app.ingestion.chunking.base import count_tokens
from app.ingestion.chunking.fixed_window import FixedWindowChunker
from app.ingestion.chunking.registry import get_chunker, list_chunkers
from app.ingestion.chunking.sentences import split_sentences
from app.ingestion.chunking.structure_aware import StructureAwareChunker
from app.ingestion.parsers.base import ParsedDocument, Span

_STRUCTURE_TOLERANCE = 40


def _doc(text: str, *, spans: list[Span] | None = None) -> ParsedDocument:
    return ParsedDocument(
        text=text,
        title="t",
        metadata={"source_type": "txt"},
        spans=spans or ([Span(0, len(text))] if text else []),
    )


def _long_text(sentences: int = 40) -> str:
    parts = [
        f"Sentence number {i} discusses payment outages and related services."
        for i in range(sentences)
    ]
    return " ".join(parts)


def test_sentence_splitter_respects_abbreviations() -> None:
    text = "Dr. Smith arrived at 9 a.m. Then the system failed. Done."
    sents = split_sentences(text)
    joined = " ".join(s.text.strip() for s in sents)
    assert "Dr. Smith" in sents[0].text
    assert any("system failed" in s.text for s in sents)
    assert text[sents[0].start : sents[0].end]
    assert joined  # non-empty


def test_registry() -> None:
    assert set(list_chunkers()) == {"fixed_window", "structure_aware"}
    assert get_chunker("fixed_window").name == "fixed_window"
    with pytest.raises(ValueError):
        get_chunker("unknown")


@pytest.mark.parametrize("strategy", ["fixed_window", "structure_aware"])
@pytest.mark.parametrize(
    "text",
    [
        _long_text(30),
        "Short doc.",
        "# Title\n\n" + _long_text(25),
        "Para one.\n\nPara two has more words about outages.\n\n" + _long_text(20),
    ],
)
def test_chunker_properties(strategy: str, text: str) -> None:
    chunk_tokens = 50
    overlap = 10
    doc = _doc(text)
    chunker = get_chunker(strategy)
    chunks = chunker.chunk(doc, chunk_tokens=chunk_tokens, overlap_tokens=overlap)

    assert chunks, "expected at least one chunk"
    assert all(c.text.strip() for c in chunks), "no empty chunks"
    assert all(doc.text[c.char_start : c.char_end] == c.text for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    # Coverage: union of ranges covers [0, len(text)]
    covered = [False] * len(text)
    for c in chunks:
        for i in range(c.char_start, c.char_end):
            covered[i] = True
    assert all(covered), f"{strategy} failed full coverage"

    # Size bound
    for c in chunks:
        if strategy == "fixed_window":
            assert c.token_count <= chunk_tokens + 5
        else:
            assert c.token_count <= chunk_tokens + _STRUCTURE_TOLERANCE

    # Deterministic
    again = chunker.chunk(doc, chunk_tokens=chunk_tokens, overlap_tokens=overlap)
    assert [(c.char_start, c.char_end, c.text) for c in chunks] == [
        (c.char_start, c.char_end, c.text) for c in again
    ]


def test_fixed_window_overlap_behavior() -> None:
    text = " ".join(f"w{i}" for i in range(100))
    chunks = FixedWindowChunker().chunk(_doc(text), chunk_tokens=20, overlap_tokens=5)
    assert len(chunks) >= 2
    # Adjacent windows should overlap in character space
    assert chunks[0].char_end > chunks[1].char_start


def test_structure_aware_uses_heading_path() -> None:
    text = (
        "# Alpha\n\n"
        + " ".join(f"Alpha sentence {i}." for i in range(15))
        + "\n\n# Beta\n\n"
        + " ".join(f"Beta sentence {i}." for i in range(15))
    )
    spans = [
        Span(0, text.index("# Beta"), heading_path="Alpha"),
        Span(text.index("# Beta"), len(text), heading_path="Beta"),
    ]
    chunks = StructureAwareChunker().chunk(
        _doc(text, spans=spans),
        chunk_tokens=40,
        overlap_tokens=5,
    )
    assert chunks
    assert any(c.heading_path == "Alpha" for c in chunks)
    assert any(c.heading_path == "Beta" for c in chunks)
    assert all(c.strategy == "structure_aware" for c in chunks)


def test_count_tokens() -> None:
    assert count_tokens("") == 0
    assert count_tokens("one two three") == 3


def test_empty_document_yields_no_chunks() -> None:
    assert FixedWindowChunker().chunk(_doc("   ")) == []
    assert StructureAwareChunker().chunk(_doc("")) == []
