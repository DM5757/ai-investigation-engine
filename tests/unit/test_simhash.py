"""Unit tests for SimHash near-duplicate fingerprinting."""

from __future__ import annotations

from app.ingestion.dedup.hashing import content_hash
from app.ingestion.dedup.simhash import (
    NUM_BANDS,
    band_values,
    compute_simhash,
    find_near_duplicates,
    hamming_distance,
    shingles,
    tokenize,
)


def test_tokenize_and_shingles() -> None:
    tokens = tokenize("The quick brown fox jumps over the lazy dog again today")
    assert "quick" in tokens
    grams = shingles(tokens, size=5)
    assert grams[0] == " ".join(tokens[:5])
    assert len(grams) == len(tokens) - 4


def test_identical_texts_same_simhash() -> None:
    text = "alpha bravo charlie delta echo foxtrot golf hotel india"
    assert compute_simhash(text) == compute_simhash(text)
    assert content_hash(text) == content_hash(text)


def test_handmade_near_duplicate_pair() -> None:
    """Two hand-made texts that differ by a tiny edit should be near-dups."""
    base = ("the quick brown fox jumps over the lazy dog " * 8).strip()
    near = base.replace("lazy dog", "lazy dogs", 1)
    far = ("recipe chocolate cake flour sugar eggs butter " * 8).strip()
    h_base = compute_simhash(base)
    h_near = compute_simhash(near)
    h_far = compute_simhash(far)
    dist_near = hamming_distance(h_base, h_near)
    dist_far = hamming_distance(h_base, h_far)
    assert dist_near <= 3
    assert dist_far > 3


def test_bands_are_four_16bit_values() -> None:
    fp = compute_simhash("one two three four five six seven eight nine ten")
    bands = band_values(fp)
    assert len(bands) == NUM_BANDS == 4
    assert all(0 <= b < (1 << 16) for b in bands)
    # Reconstruct fingerprint from bands (MSB first).
    rebuilt = 0
    for b in bands:
        rebuilt = (rebuilt << 16) | b
    assert rebuilt == fp


def test_find_near_duplicates_orders_by_distance() -> None:
    target = compute_simhash(
        "system change caused payment disruption in march affecting billing"
    )
    close = compute_simhash(
        "system change caused payment disruption in march affecting billing ops"
    )
    candidates = [
        ("far", compute_simhash("completely unrelated gardening tips for roses")),
        ("close", close),
    ]
    hits = find_near_duplicates(target, candidates, threshold=8)
    assert hits
    assert hits[0][0] == "close"
