"""Unit tests for deterministic eval metrics."""

from __future__ import annotations

from eval.metrics import (
    all_gold_at_k,
    citation_accuracy,
    exact_match,
    mrr,
    multi_doc_coverage,
    normalize_answer,
    recall_at_k,
    token_f1,
)


def test_normalize_and_exact_match() -> None:
    assert normalize_answer("The Answer!") == "the answer"
    assert exact_match("Paris", "paris") == 1.0
    assert exact_match("Paris", "London") == 0.0


def test_token_f1_partial() -> None:
    score = token_f1("the cat sat", "cat sat here")
    assert 0.0 < score < 1.0


def test_retrieval_metrics() -> None:
    retrieved = ["a", "b", "c", "d"]
    gold = ["c", "z"]
    assert recall_at_k(retrieved, gold, 3) == 0.5
    assert all_gold_at_k(retrieved, gold, 3) == 0.0
    assert all_gold_at_k(["c", "z", "a"], gold, 3) == 1.0
    assert mrr(retrieved, gold) == 1.0 / 3
    assert multi_doc_coverage(["d1", "d2", "d1"], ["d1", "d3"], 3) == 0.5


def test_citation_accuracy() -> None:
    metrics = citation_accuracy(["d1", "d2"], ["d1", "d3"])
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert 0.0 < metrics["f1"] <= 1.0
