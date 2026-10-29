"""64-bit SimHash with 5-word shingles and 4×16-bit bands."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")

SHINGLE_SIZE = 5
BIT_WIDTH = 64
BAND_BITS = 16
NUM_BANDS = BIT_WIDTH // BAND_BITS  # 4


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens (apostrophes inside words kept)."""
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


def shingles(tokens: list[str], size: int = SHINGLE_SIZE) -> list[str]:
    """Overlapping word n-grams; shorter texts yield a single joined shingle."""
    if not tokens:
        return []
    if len(tokens) < size:
        return [" ".join(tokens)]
    return [" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)]


def _feature_hash(feature: str) -> int:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def compute_simhash(text: str) -> int:
    """Compute a 64-bit SimHash fingerprint from 5-word shingles."""
    feats = shingles(tokenize(text))
    if not feats:
        return 0
    weights = [0] * BIT_WIDTH
    for feat in feats:
        h = _feature_hash(feat)
        for bit in range(BIT_WIDTH):
            if (h >> bit) & 1:
                weights[bit] += 1
            else:
                weights[bit] -= 1
    fingerprint = 0
    for bit, w in enumerate(weights):
        if w > 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two 64-bit fingerprints."""
    return (a ^ b).bit_count()


def band_values(fingerprint: int) -> list[int]:
    """Split a 64-bit fingerprint into four 16-bit band values (MSB first)."""
    mask = (1 << BAND_BITS) - 1
    bands: list[int] = []
    for i in range(NUM_BANDS):
        shift = BIT_WIDTH - BAND_BITS * (i + 1)
        bands.append((fingerprint >> shift) & mask)
    return bands


def find_near_duplicates(
    fingerprint: int,
    candidates: Iterable[tuple[str, int]],
    *,
    threshold: int,
) -> list[tuple[str, int]]:
    """Return (doc_id, distance) pairs with Hamming distance <= threshold."""
    hits: list[tuple[str, int]] = []
    for doc_id, other in candidates:
        dist = hamming_distance(fingerprint, other)
        if dist <= threshold:
            hits.append((doc_id, dist))
    hits.sort(key=lambda item: (item[1], item[0]))
    return hits
