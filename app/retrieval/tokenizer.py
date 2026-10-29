"""Query/document tokenizer for BM25 sparse encoding."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import Stemmer

# Small English stop-word list (intentionally tiny; custom component, not NLTK).
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "it",
        "this",
        "that",
        "with",
        "as",
        "by",
        "from",
        "not",
        "no",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "my",
        "your",
        "his",
        "her",
        "our",
        "their",
        "its",
    }
)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@lru_cache(maxsize=1)
def _stemmer() -> Stemmer.Stemmer:
    return Stemmer.Stemmer("english")


def tokenize(text: str, *, stem: bool = True) -> list[str]:
    """Lowercase, NFKC-normalize, extract ``\\w+``, drop stopwords, optionally stem.

    Returns an ordered list of tokens (duplicates preserved for TF).
    """
    if not text:
        return []
    normalized = unicodedata.normalize("NFKC", text).lower()
    raw = _TOKEN_RE.findall(normalized)
    stemmer = _stemmer() if stem else None
    out: list[str] = []
    for tok in raw:
        if tok in _STOPWORDS:
            continue
        if stemmer is not None:
            tok = stemmer.stemWord(tok)
        if tok:
            out.append(tok)
    return out
