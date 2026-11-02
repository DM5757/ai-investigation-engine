"""Citation marker parsing shared by synthesis, verification, and scoring.

Supports:
  [S1]  [S1][S2]  [S1, S2]  [S1; S2]  [S1,S2]
  fullwidth brackets ［S1］
  invisible separators (ZWSP/BOM) inside markers

Malformed citation-like tokens are detected so they can be rejected rather
than silently ignored by verifiers that only looked for ``[S\\d+]``.
"""

from __future__ import annotations

import re
import unicodedata

_INVISIBLE = "\u200b\u200c\u200d\ufeff\u2060"
_INVISIBLE_RE = re.compile(f"[{re.escape(_INVISIBLE)}]")
_FULLWIDTH_BRACKETS = str.maketrans({"\uff3b": "[", "\uff3d": "]"})

_LABEL = r"S\d+"
_SEP = r"[\s,;|/·•]+"
_GROUP_INNER = rf"{_LABEL}(?:{_SEP}{_LABEL})*"
_CITATION_GROUP_RE = re.compile(rf"\[\s*({_GROUP_INNER})\s*\]", re.IGNORECASE)

_MALFORMED_CITE_RE = re.compile(
    r"\["
    r"(?:"
    r"S(?!\d)"
    r"|S\d+[A-Za-z]"
    r"|[A-RT-Z]\d+"
    r"|source\s*\d+"
    r"|cite\s*\d+"
    r"|ref\s*\d+"
    r")"
    r"[^\]]*"
    r"\]",
    re.IGNORECASE,
)

_LABEL_TOKEN_RE = re.compile(r"[Ss](\d+)")


def _canon_label(raw: str) -> str:
    m = _LABEL_TOKEN_RE.fullmatch(raw) or _LABEL_TOKEN_RE.search(raw)
    if not m:
        return raw.upper()
    return f"S{m.group(1)}"


def normalize_citation_text(text: str) -> str:
    """NFKC + strip invisibles + ASCII-ify fullwidth brackets."""
    t = unicodedata.normalize("NFKC", text)
    t = _INVISIBLE_RE.sub("", t)
    return t.translate(_FULLWIDTH_BRACKETS)


def extract_citation_labels(text: str | None) -> set[str]:
    """Return canonical ``S{n}`` labels referenced in ``text``."""
    if not text:
        return set()
    t = normalize_citation_text(text)
    labels: set[str] = set()
    for match in _CITATION_GROUP_RE.finditer(t):
        for part in _LABEL_TOKEN_RE.finditer(match.group(1)):
            labels.add(f"S{part.group(1)}")
    return labels


def find_malformed_citations(text: str | None) -> list[str]:
    """Return raw malformed citation-like spans (not valid Sn groups)."""
    if not text:
        return []
    t = normalize_citation_text(text)
    valid_spans = [m.span() for m in _CITATION_GROUP_RE.finditer(t)]
    out: list[str] = []
    for m in _MALFORMED_CITE_RE.finditer(t):
        if any(s <= m.start() and m.end() <= e for s, e in valid_spans):
            continue
        out.append(m.group(0))
    return out


def strip_citation_markers(text: str | None) -> str:
    """Remove valid and malformed citation markers for answer scoring."""
    if not text:
        return ""
    t = normalize_citation_text(text)
    t = _CITATION_GROUP_RE.sub(" ", t)
    t = _MALFORMED_CITE_RE.sub(" ", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    return t.strip()


def strip_disallowed_citations(
    answer: str,
    allowed: set[str],
) -> tuple[str, list[str]]:
    """Remove citation groups that reference any label outside ``allowed``.

    Also strips malformed citation-like tokens. Returns (cleaned, removed_labels).
    """
    t = normalize_citation_text(answer)
    removed: list[str] = []

    def _repl_group(match: re.Match[str]) -> str:
        canon = [f"S{m.group(1)}" for m in _LABEL_TOKEN_RE.finditer(match.group(1))]
        bad = [lab for lab in canon if lab not in allowed]
        if not bad and canon:
            return match.group(0)
        removed.extend(bad if bad else canon)
        return ""

    cleaned = _CITATION_GROUP_RE.sub(_repl_group, t)
    for bad in find_malformed_citations(cleaned):
        removed.append(bad)
        cleaned = cleaned.replace(bad, "", 1)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, removed


__all__ = [
    "extract_citation_labels",
    "find_malformed_citations",
    "normalize_citation_text",
    "strip_citation_markers",
    "strip_disallowed_citations",
]
