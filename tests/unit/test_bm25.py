"""Hand-computed BM25 sparse encoder unit tests."""

from __future__ import annotations

import zlib

from app.retrieval.bm25_sparse import Bm25Encoder, bm25_tf_weight, term_id
from app.retrieval.tokenizer import tokenize


def test_tokenize_lowercase_stopwords_stem() -> None:
    tokens = tokenize("The Failures of Systems")
    assert "the" not in tokens
    assert "failur" in tokens  # Snowball stem of failures
    assert "system" in tokens


def test_term_id_stable_crc32_not_python_hash() -> None:
    expected = zlib.crc32(b"zymopolymer") & 0xFFFFFFFF
    assert term_id("zymopolymer") == expected
    assert term_id("zymopolymer") == term_id("zymopolymer")


def test_bm25_tf_weight_hand_computed() -> None:
    """tf=1, dl=3, avgdl=100, k1=1.2, b=0.75 → 2.2 / 1.327."""
    # denom = 1 + 1.2 * (1 - 0.75 + 0.75 * 3/100)
    #       = 1 + 1.2 * 0.2725 = 1.327
    # weight = 1 * 2.2 / 1.327 ≈ 1.6578749058
    expected = 2.2 / 1.327
    got = bm25_tf_weight(1.0, 3.0, avgdl=100.0, k1=1.2, b=0.75)
    assert abs(got - expected) < 1e-12


def test_bm25_tf_weight_repeated_term() -> None:
    """tf=2, dl=4, avgdl=10, k1=1.2, b=0.75 hand formula."""
    # denom = 2 + 1.2 * (1 - 0.75 + 0.75 * 4/10)
    #       = 2 + 1.2 * (0.25 + 0.3) = 2 + 1.2 * 0.55 = 2.66
    # weight = 2 * 2.2 / 2.66 = 4.4 / 2.66
    expected = 4.4 / 2.66
    got = bm25_tf_weight(2.0, 4.0, avgdl=10.0, k1=1.2, b=0.75)
    assert abs(got - expected) < 1e-12


def test_encode_document_matches_hand_weights() -> None:
    enc = Bm25Encoder(k1=1.2, b=0.75, avgdl=100.0)
    sparse = enc.encode_document("cat sat mat")
    # three unique terms, each tf=1, dl=3 → same weight
    expected_w = bm25_tf_weight(1.0, 3.0, avgdl=100.0, k1=1.2, b=0.75)
    assert len(sparse.indices) == 3
    assert all(abs(v - expected_w) < 1e-12 for v in sparse.values)
    assert sparse.indices == sorted(sparse.indices)
    assert set(sparse.indices) == {term_id("cat"), term_id("sat"), term_id("mat")}


def test_encode_query_unique_weight_one() -> None:
    enc = Bm25Encoder()
    sparse = enc.encode_query("cat cat mat")
    assert set(sparse.values) == {1.0}
    assert len(sparse.indices) == 2
    assert set(sparse.indices) == {term_id("cat"), term_id("mat")}
