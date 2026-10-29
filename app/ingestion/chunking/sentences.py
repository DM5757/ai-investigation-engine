"""Sentence splitter with abbreviation-aware boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Common English abbreviations that should not end a sentence at the period.
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "etc",
        "e.g",
        "i.e",
        "approx",
        "dept",
        "fig",
        "al",
        "inc",
        "ltd",
        "co",
        "no",
        "vol",
        "pp",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
        "u.s",
        "u.k",
        "a.m",
        "p.m",
    }
)

_BOUNDARY_RE = re.compile(r"([.!?]+)(\s+|$)")
_WORD_BEFORE_RE = re.compile(r"([A-Za-z][A-Za-z.\-]*)\s*$")


@dataclass(frozen=True, slots=True)
class Sentence:
    """Sentence with offsets into the original text."""

    start: int
    end: int
    text: str


def split_sentences(text: str) -> list[Sentence]:
    """Split ``text`` into sentences, respecting abbreviation periods."""
    if not text:
        return []
    if not text.strip():
        return []

    sentences: list[Sentence] = []
    start = 0
    for match in _BOUNDARY_RE.finditer(text):
        end = match.end(1)
        candidate = text[start:end]
        if not candidate.strip():
            start = match.end()
            continue
        if _ends_with_abbreviation(candidate):
            continue
        sentences.append(Sentence(start=start, end=end, text=candidate.strip()))
        start = match.end()

    if start < len(text):
        tail = text[start:]
        if tail.strip():
            sentences.append(Sentence(start=start, end=len(text), text=tail.strip()))

    if not sentences and text.strip():
        sentences.append(Sentence(start=0, end=len(text), text=text.strip()))

    # Extend ends so consecutive sentences abut (cover interstitial whitespace).
    adjusted: list[Sentence] = []
    for idx, sent in enumerate(sentences):
        end = sentences[idx + 1].start if idx + 1 < len(sentences) else len(text)
        start_i = 0 if idx == 0 else sent.start
        adjusted.append(Sentence(start=start_i, end=end, text=text[start_i:end]))
    return adjusted


def _ends_with_abbreviation(fragment: str) -> bool:
    stripped = fragment.rstrip()
    if not stripped.endswith("."):
        return False
    # Strip trailing periods for lookup (handles "U.S." / "e.g.").
    match = _WORD_BEFORE_RE.search(stripped[:-1] + " ")
    if not match:
        # Check last token including internal dots.
        token = stripped.split()[-1] if stripped.split() else ""
        key = token.rstrip(".").lower()
        return key in ABBREVIATIONS
    key = match.group(1).rstrip(".").lower()
    return key in ABBREVIATIONS
