"""Custom BM25 sparse encoder with stable 32-bit term ids."""

from __future__ import annotations

import zlib
from collections import Counter
from dataclasses import dataclass

from app.retrieval.tokenizer import tokenize


def term_id(term: str) -> int:
    """Stable unsigned 32-bit id via zlib.crc32 of UTF-8 bytes (survives restarts).

    Intentionally not ``hash()`` — Python's hash is randomised per process.
    """
    return zlib.crc32(term.encode("utf-8")) & 0xFFFFFFFF


def bm25_tf_weight(
    tf: float,
    dl: float,
    *,
    avgdl: float,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    """BM25 term-frequency component (no IDF; IDF left to Qdrant sparse modifier).

    weight = tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
    """
    if tf <= 0 or dl <= 0 or avgdl <= 0:
        return 0.0
    denom = tf + k1 * (1.0 - b + b * (dl / avgdl))
    if denom == 0.0:
        return 0.0
    return (tf * (k1 + 1.0)) / denom


@dataclass
class SparseVector:
    """Parallel sparse indices/values for Qdrant."""

    indices: list[int]
    values: list[float]

    def __post_init__(self) -> None:
        if len(self.indices) != len(self.values):
            raise ValueError("indices and values length mismatch")


class Bm25Encoder:
    """Encode documents/queries as BM25-weighted sparse vectors."""

    def __init__(
        self,
        *,
        k1: float = 1.2,
        b: float = 0.75,
        avgdl: float = 100.0,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.avgdl = avgdl

    def encode_document(self, text: str) -> SparseVector:
        tokens = tokenize(text)
        if not tokens:
            return SparseVector([], [])
        counts = Counter(tokens)
        dl = float(len(tokens))
        pairs: list[tuple[int, float]] = []
        for term, tf in counts.items():
            weight = bm25_tf_weight(
                float(tf),
                dl,
                avgdl=self.avgdl,
                k1=self.k1,
                b=self.b,
            )
            if weight > 0.0:
                pairs.append((term_id(term), weight))
        pairs.sort(key=lambda p: p[0])
        return SparseVector([i for i, _ in pairs], [v for _, v in pairs])

    def encode_query(self, text: str) -> SparseVector:
        """Query side: unique terms with weight 1.0 (tf=1 style)."""
        tokens = tokenize(text)
        if not tokens:
            return SparseVector([], [])
        seen: set[str] = set()
        pairs: list[tuple[int, float]] = []
        for term in tokens:
            if term in seen:
                continue
            seen.add(term)
            pairs.append((term_id(term), 1.0))
        pairs.sort(key=lambda p: p[0])
        return SparseVector([i for i, _ in pairs], [v for _, v in pairs])
