"""Deterministic retrieval and answer-quality metrics."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from app.investigation.citations import strip_citation_markers

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_answer(text: str, *, strip_citations: bool = True) -> str:
    """Lowercase, strip punctuation, collapse whitespace (Hotpot-style).

    By default citation markers ([S1], [S1, S2], …) are removed before
    normalization so EM/token F1 score answer content, not citation syntax.
    """
    t = strip_citation_markers(text) if strip_citations else text
    t = t.lower().strip()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def tokenize(text: str, *, strip_citations: bool = True) -> list[str]:
    norm = normalize_answer(text, strip_citations=strip_citations)
    return [tok for tok in norm.split(" ") if tok]


def exact_match(prediction: str, gold: str, *, strip_citations: bool = True) -> float:
    return (
        1.0
        if normalize_answer(prediction, strip_citations=strip_citations)
        == normalize_answer(gold, strip_citations=strip_citations)
        else 0.0
    )


def token_f1(prediction: str, gold: str, *, strip_citations: bool = True) -> float:
    pred_toks = tokenize(prediction, strip_citations=strip_citations)
    gold_toks = tokenize(gold, strip_citations=strip_citations)
    if not pred_toks and not gold_toks:
        return 1.0
    if not pred_toks or not gold_toks:
        return 0.0
    common: dict[str, int] = {}
    for tok in gold_toks:
        common[tok] = common.get(tok, 0) + 1
    overlap = 0
    for tok in pred_toks:
        n = common.get(tok, 0)
        if n > 0:
            overlap += 1
            common[tok] = n - 1
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_toks)
    recall = overlap / len(gold_toks)
    return 2 * precision * recall / (precision + recall)


def recall_at_k(retrieved_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> float:
    if not gold_ids:
        return 0.0
    top = set(retrieved_ids[:k])
    hits = sum(1 for g in gold_ids if g in top)
    return hits / len(gold_ids)


def all_gold_at_k(retrieved_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> float:
    if not gold_ids:
        return 0.0
    top = set(retrieved_ids[:k])
    return 1.0 if all(g in top for g in gold_ids) else 0.0


def mrr(retrieved_ids: Sequence[str], gold_ids: Sequence[str]) -> float:
    gold = set(gold_ids)
    if not gold:
        return 0.0
    for i, rid in enumerate(retrieved_ids, start=1):
        if rid in gold:
            return 1.0 / i
    return 0.0


def multi_doc_coverage(
    retrieved_doc_ids: Sequence[str],
    gold_doc_ids: Sequence[str],
    k: int,
) -> float:
    """Fraction of distinct gold documents appearing in top-k retrieved docs."""
    if not gold_doc_ids:
        return 0.0
    top_docs = set(retrieved_doc_ids[:k])
    hits = sum(1 for g in set(gold_doc_ids) if g in top_docs)
    return hits / len(set(gold_doc_ids))


def citation_accuracy(
    cited_doc_ids: Sequence[str],
    gold_doc_ids: Sequence[str],
) -> dict[str, float]:
    """Precision/recall of cited docs vs gold supporting docs."""
    cited = [c for c in cited_doc_ids if c]
    gold = set(g for g in gold_doc_ids if g)
    if not cited and not gold:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not cited:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    if not gold:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    hit = sum(1 for c in set(cited) if c in gold)
    precision = hit / len(set(cited))
    recall = hit / len(gold)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


def gold_coverage(
    stage_doc_ids: Sequence[str],
    gold_doc_ids: Sequence[str],
) -> dict[str, float | int]:
    """Eval-only: how many gold docs remain at a pipeline stage."""
    gold = list(dict.fromkeys(g for g in gold_doc_ids if g))
    present = list(dict.fromkeys(d for d in stage_doc_ids if d))
    if not gold:
        return {"n_gold": 0, "n_present": 0, "recall": 0.0, "all_present": 0.0}
    gold_set = set(gold)
    n_present = sum(1 for d in present if d in gold_set)
    return {
        "n_gold": len(gold),
        "n_present": n_present,
        "recall": n_present / len(gold),
        "all_present": 1.0 if n_present == len(gold) else 0.0,
    }
