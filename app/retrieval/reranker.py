"""Custom linear feature reranker with diversification and caps."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.retrieval.tokenizer import tokenize
from app.retrieval.types import RetrievalHit, ScoredChunk

_CAP_ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z0-9_-]{1,}\b")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


@dataclass(frozen=True)
class RerankerWeights:
    """Linear weights for explainable reranker features."""

    fused: float = 0.40
    coverage: float = 0.20
    title_heading: float = 0.15
    entity_number: float = 0.15
    proximity: float = 0.10
    mmr_lambda: float = 0.7


def feature_fused_score(chunk: ScoredChunk, *, max_score: float) -> float:
    """Normalise fused score into [0, 1] using the list max."""
    if max_score <= 0.0:
        return 0.0
    return max(0.0, min(1.0, chunk.score / max_score))


def feature_query_coverage(query: str, text: str) -> float:
    """Fraction of unique query tokens present in the chunk text."""
    q_terms = set(tokenize(query))
    if not q_terms:
        return 0.0
    t_terms = set(tokenize(text))
    return len(q_terms & t_terms) / len(q_terms)


def feature_title_heading_match(query: str, title: str | None, heading: str | None) -> float:
    """Overlap of query tokens with title and/or heading path."""
    q_terms = set(tokenize(query))
    if not q_terms:
        return 0.0
    fields = " ".join(p for p in (title or "", heading or "") if p)
    if not fields.strip():
        return 0.0
    f_terms = set(tokenize(fields))
    return len(q_terms & f_terms) / len(q_terms)


def feature_entity_number_overlap(query: str, text: str) -> float:
    """Overlap of entities/numbers, with extra weight for multi-token phrases.

    Multi-token proper phrases (and hyphenated compounds) must match as a unit;
    a single shared token cannot dominate when the query names a longer entity.
    """
    q_ents = set(_CAP_ENTITY_RE.findall(query)) | set(_NUMBER_RE.findall(query))
    phrases = _multi_token_phrases(query)
    t_lower_text = text.lower()
    t_caps = set(_CAP_ENTITY_RE.findall(text))
    t_nums = set(_NUMBER_RE.findall(text))
    t_lower = {t.lower() for t in tokenize(text, stem=False)}

    phrase_score = 0.0
    if phrases:
        phrase_hits = 0.0
        for phrase in phrases:
            parts = [p for p in re.split(r"[\s\-–—]+", phrase.lower()) if len(p) > 2]
            if not parts:
                continue
            covered = sum(1 for p in parts if p in t_lower_text)
            ratio = covered / len(parts)
            if ratio >= 0.6:
                phrase_hits = max(phrase_hits, ratio)
        phrase_score = phrase_hits

    token_score = 0.0
    if q_ents:
        hits = 0
        for ent in q_ents:
            if ent in t_caps or ent in t_nums or ent.lower() in t_lower:
                hits += 1
        token_score = hits / len(q_ents)

    if phrases:
        # Phrase agreement dominates; lone token overlap is capped when phrases miss.
        if phrase_score >= 0.6:
            return min(1.0, 0.65 * phrase_score + 0.35 * token_score)
        return min(0.4, 0.25 * phrase_score + 0.2 * token_score)
    return token_score


def _multi_token_phrases(query: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(
        r"\b([A-Z][A-Za-z0-9]*(?:[\s\-–—][A-Z][A-Za-z0-9]*)+)\b",
        query,
    ):
        found.append(match.group(1))
    for match in re.finditer(
        r"\b([A-Za-z][A-Za-z0-9]*(?:[\-–—][A-Za-z][A-Za-z0-9]*){1,})\b",
        query,
    ):
        found.append(match.group(1))
    # Unique, longest first
    uniq: list[str] = []
    seen: set[str] = set()
    for phrase in sorted(found, key=lambda p: (-len(p), p)):
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(phrase)
    return uniq[:6]


def feature_proximity(query: str, text: str) -> float:
    """Bonus when query terms appear close together in the chunk.

    Uses minimum window covering all matched query stems; closer → higher.
    """
    q_terms = list(dict.fromkeys(tokenize(query)))
    if len(q_terms) < 2:
        return 1.0 if q_terms and q_terms[0] in set(tokenize(text)) else 0.0
    tokens = tokenize(text)
    if not tokens:
        return 0.0
    positions: dict[str, list[int]] = {t: [] for t in q_terms}
    for i, tok in enumerate(tokens):
        if tok in positions:
            positions[tok].append(i)
    if any(not positions[t] for t in q_terms):
        # Partial: score by fraction of terms present, diluted.
        present = sum(1 for t in q_terms if positions[t])
        return 0.25 * (present / len(q_terms))
    # Greedy min window over ordered unique terms.
    window = _min_cover_window(positions, q_terms)
    if window is None:
        return 0.0
    span = window[1] - window[0] + 1
    ideal = len(q_terms)
    return max(0.0, min(1.0, ideal / span))


def _min_cover_window(
    positions: dict[str, list[int]],
    terms: Sequence[str],
) -> tuple[int, int] | None:
    """Smallest inclusive index window covering one occurrence of each term."""
    # Flatten candidates and two-pointer over sorted unique positions.
    all_pos: list[tuple[int, str]] = []
    for term in terms:
        for p in positions[term]:
            all_pos.append((p, term))
    all_pos.sort(key=lambda x: x[0])
    need = len(terms)
    have: dict[str, int] = {}
    best: tuple[int, int] | None = None
    left = 0
    for right, (pos, term) in enumerate(all_pos):
        have[term] = have.get(term, 0) + 1
        while len(have) == need and left <= right:
            start = all_pos[left][0]
            end = pos
            if best is None or (end - start) < (best[1] - best[0]):
                best = (start, end)
            drop = all_pos[left][1]
            have[drop] -= 1
            if have[drop] == 0:
                del have[drop]
            left += 1
    return best


def score_features(
    query: str,
    chunk: ScoredChunk,
    *,
    max_fused: float,
    weights: RerankerWeights,
) -> tuple[float, dict[str, float]]:
    """Compute weighted linear score and per-feature breakdown."""
    feats = {
        "fused": feature_fused_score(chunk, max_score=max_fused),
        "coverage": feature_query_coverage(query, chunk.text),
        "title_heading": feature_title_heading_match(
            query, chunk.title, chunk.heading_path
        ),
        "entity_number": feature_entity_number_overlap(query, chunk.text),
        "proximity": feature_proximity(query, chunk.text),
    }
    total = (
        weights.fused * feats["fused"]
        + weights.coverage * feats["coverage"]
        + weights.title_heading * feats["title_heading"]
        + weights.entity_number * feats["entity_number"]
        + weights.proximity * feats["proximity"]
    )
    return total, feats


def _token_jaccard(a: str, b: str) -> float:
    sa, sb = set(tokenize(a)), set(tokenize(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def diversify_mmr(
    scored: Sequence[tuple[ScoredChunk, float, dict[str, float]]],
    *,
    mmr_lambda: float,
    limit: int,
) -> list[tuple[ScoredChunk, float, dict[str, float]]]:
    """MMR-style selection using token Jaccard as similarity proxy."""
    remaining = list(scored)
    selected: list[tuple[ScoredChunk, float, dict[str, float]]] = []
    while remaining and len(selected) < limit:
        best_i = 0
        best_val = -math.inf
        for i, (chunk, rel, _feats) in enumerate(remaining):
            if not selected:
                mmr = rel
            else:
                sim = max(_token_jaccard(chunk.text, s[0].text) for s in selected)
                mmr = mmr_lambda * rel - (1.0 - mmr_lambda) * sim
            if mmr > best_val or (
                math.isclose(mmr, best_val) and chunk.chunk_id < remaining[best_i][0].chunk_id
            ):
                best_val = mmr
                best_i = i
        selected.append(remaining.pop(best_i))
    return selected


def collapse_near_duplicates(
    items: Sequence[tuple[ScoredChunk, float, dict[str, float]]],
) -> list[tuple[ScoredChunk, float, dict[str, float]]]:
    """Drop chunks whose near_duplicate_of points at a doc already kept."""
    kept_docs: set[str] = set()
    out: list[tuple[ScoredChunk, float, dict[str, float]]] = []
    for item in items:
        chunk = item[0]
        nd = chunk.near_duplicate_of
        if nd is not None and nd in kept_docs:
            continue
        out.append(item)
        kept_docs.add(chunk.doc_id)
    return out


def apply_per_doc_cap(
    items: Sequence[tuple[ScoredChunk, float, dict[str, float]]],
    *,
    per_doc_cap: int,
) -> list[tuple[ScoredChunk, float, dict[str, float]]]:
    """Keep at most ``per_doc_cap`` chunks per document (order preserved)."""
    if per_doc_cap <= 0:
        return list(items)
    counts: dict[str, int] = {}
    out: list[tuple[ScoredChunk, float, dict[str, float]]] = []
    for item in items:
        doc_id = item[0].doc_id
        n = counts.get(doc_id, 0)
        if n >= per_doc_cap:
            continue
        counts[doc_id] = n + 1
        out.append(item)
    return out


def rerank(
    query: str,
    chunks: Sequence[ScoredChunk],
    *,
    weights: RerankerWeights | None = None,
    per_doc_cap: int = 3,
    limit: int | None = None,
) -> list[RetrievalHit]:
    """Score, diversify, collapse near-dups, and cap per document."""
    if not chunks:
        return []
    w = weights or RerankerWeights()
    max_fused = max(c.score for c in chunks) or 1.0
    scored: list[tuple[ScoredChunk, float, dict[str, float]]] = []
    for chunk in chunks:
        total, feats = score_features(query, chunk, max_fused=max_fused, weights=w)
        scored.append((chunk, total, feats))
    scored.sort(key=lambda t: (-t[1], t[0].chunk_id))
    take = limit if limit is not None else len(scored)
    diversified = diversify_mmr(scored, mmr_lambda=w.mmr_lambda, limit=max(take * 3, take))
    collapsed = collapse_near_duplicates(diversified)
    capped = apply_per_doc_cap(collapsed, per_doc_cap=per_doc_cap)
    capped = capped[:take]
    hits: list[RetrievalHit] = []
    for chunk, total, feats in capped:
        hits.append(
            RetrievalHit(
                chunk=ScoredChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    version=chunk.version,
                    text=chunk.text,
                    score=total,
                    chunk_index=chunk.chunk_index,
                    title=chunk.title,
                    heading_path=chunk.heading_path,
                    near_duplicate_of=chunk.near_duplicate_of,
                    content_hash=chunk.content_hash,
                    payload=dict(chunk.payload),
                ),
                fused_score=chunk.score,
                feature_scores=feats,
                mode="hybrid_rerank",
            )
        )
    return hits
