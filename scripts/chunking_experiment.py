"""Compare fixed_window vs structure_aware chunking (DOC-6).

Uses synthetic long docs (gold markers) + Hotpot corpus subset.
Writes eval/results/chunking_comparison.json and .md

Usage:
  uv run python scripts/chunking_experiment.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion.chunking.registry import get_chunker  # noqa: E402
from app.ingestion.normalize import normalize_text  # noqa: E402
from app.ingestion.parsers.base import ParsedDocument, single_span  # noqa: E402
from app.ingestion.parsers.registry import parse_document  # noqa: E402
from scripts._phase6_common import (  # noqa: E402
    RAW_CORPUS,
    SYNTHETIC_DIR,
    SYNTHETIC_TRUTH,
    ensure_dirs,
    iter_jsonl,
    write_json,
)

RESULTS_JSON = ROOT / "eval" / "results" / "chunking_comparison.json"
RESULTS_MD = ROOT / "eval" / "results" / "chunking_comparison.md"


def _parsed_from_text(title: str, text: str) -> ParsedDocument:
    t = normalize_text(text)
    return ParsedDocument(text=t, title=title, metadata={}, spans=single_span(t))


def chunk_stats(
    docs: list[ParsedDocument],
    strategy: str,
    *,
    chunk_tokens: int,
    overlap_tokens: int,
) -> dict[str, Any]:
    chunker = get_chunker(strategy)
    t0 = time.perf_counter()
    total_chunks = 0
    lengths: list[int] = []
    for doc in docs:
        chunks = chunker.chunk(
            doc, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens
        )
        total_chunks += len(chunks)
        lengths.extend(c.token_count for c in chunks)
    wall = time.perf_counter() - t0
    return {
        "strategy": strategy,
        "documents": len(docs),
        "total_chunks": total_chunks,
        "avg_chunks_per_doc": round(total_chunks / len(docs), 3) if docs else 0,
        "avg_chunk_tokens": round(sum(lengths) / len(lengths), 2) if lengths else 0,
        "latency_seconds": round(wall, 4),
        "docs_per_second": round(len(docs) / wall, 2) if wall > 0 else None,
    }


def span_recall_at_k(
    docs: list[tuple[ParsedDocument, str, str]],
    strategy: str,
    *,
    chunk_tokens: int,
    overlap_tokens: int,
    k: int = 5,
) -> dict[str, Any]:
    """Gold marker must appear in a top-K chunk by simple lexical score.

    Proxy scorer: fraction of query tokens overlapping chunk text (no embeddings),
    so the experiment isolates chunking boundary effects.
    """
    chunker = get_chunker(strategy)
    hits = 0
    mrr_total = 0.0
    details: list[dict[str, Any]] = []
    for doc, marker, query in docs:
        chunks = chunker.chunk(
            doc, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens
        )
        q_tokens = set(query.lower().split())
        scored: list[tuple[float, int, str]] = []
        for ch in chunks:
            ctoks = set(ch.text.lower().split())
            overlap = len(q_tokens & ctoks) / max(len(q_tokens), 1)
            # Boost if marker present (oracle check separate)
            scored.append((overlap, ch.chunk_index, ch.text))
        scored.sort(key=lambda x: (-x[0], x[1]))
        top = scored[:k]
        rank = None
        for i, (_s, _idx, text) in enumerate(top, start=1):
            if marker in text:
                rank = i
                break
        # Also check if marker exists in any chunk at all
        any_chunk = any(marker in ch.text for ch in chunks)
        if rank is not None:
            hits += 1
            mrr_total += 1.0 / rank
        details.append(
            {
                "marker": marker,
                "query": query,
                "rank_in_topk": rank,
                "marker_in_any_chunk": any_chunk,
                "n_chunks": len(chunks),
            }
        )
    n = len(docs)
    return {
        "strategy": strategy,
        "n": n,
        "recall_at_k": round(hits / n, 4) if n else 0.0,
        "mrr": round(mrr_total / n, 4) if n else 0.0,
        "k": k,
        "details": details,
    }


def retrieval_proxy_hotpot(
    records: list[dict[str, Any]],
    strategy: str,
    *,
    chunk_tokens: int,
    overlap_tokens: int,
    k: int = 5,
) -> dict[str, Any]:
    """For Hotpot paragraphs: query = first 8 tokens; gold = full text must be in a chunk."""
    chunker = get_chunker(strategy)
    hits = 0
    mrr_total = 0.0
    for rec in records:
        text = str(rec.get("text") or "")
        title = str(rec.get("title") or "x")
        doc = _parsed_from_text(title, text)
        words = text.split()
        query = " ".join(words[:8]) if words else title
        # Gold: a distinctive 6-gram from the middle if long enough
        if len(words) >= 12:
            mid = len(words) // 2
            gold = " ".join(words[mid : mid + 6])
        else:
            gold = text[:80]
        chunks = chunker.chunk(
            doc, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens
        )
        q_tokens = set(query.lower().split())
        scored = []
        for ch in chunks:
            ctoks = set(ch.text.lower().split())
            overlap = len(q_tokens & ctoks) / max(len(q_tokens), 1)
            scored.append((overlap, ch.text))
        scored.sort(key=lambda x: -x[0])
        rank = None
        for i, (_s, ctext) in enumerate(scored[:k], start=1):
            if gold and gold in ctext:
                rank = i
                break
        if rank is None and len(chunks) == 1 and gold in chunks[0].text:
            rank = 1
        if rank is not None:
            hits += 1
            mrr_total += 1.0 / rank
    n = len(records)
    return {
        "strategy": strategy,
        "n": n,
        "recall_at_k": round(hits / n, 4) if n else 0.0,
        "mrr": round(mrr_total / n, 4) if n else 0.0,
        "k": k,
        "metric": "lexical_proxy_midgram",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunking strategy comparison")
    parser.add_argument("--chunk-tokens", type=int, default=200)
    parser.add_argument("--overlap-tokens", type=int, default=40)
    parser.add_argument("--hotpot-sample", type=int, default=100)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    ensure_dirs()

    # Synthetic long doc + gold markers
    gold_docs: list[tuple[ParsedDocument, str, str]] = []
    if SYNTHETIC_TRUTH.exists():
        truth = json.loads(SYNTHETIC_TRUTH.read_text(encoding="utf-8"))
        for g in truth.get("chunking_gold_spans") or []:
            path = ROOT / g["doc"]
            if not path.exists():
                continue
            data = path.read_bytes()
            parsed = parse_document(path.name, data)
            gold_docs.append(
                (
                    ParsedDocument(
                        text=normalize_text(parsed.text),
                        title=parsed.title,
                        metadata=dict(parsed.metadata),
                        spans=list(parsed.spans),
                    ),
                    str(g["marker"]),
                    str(g["query"]),
                )
            )
    else:
        # Fallback inline
        long_path = SYNTHETIC_DIR / "long_architecture.md"
        if long_path.exists():
            parsed = parse_document(long_path.name, long_path.read_bytes())
            gold_docs.append(
                (
                    parsed,
                    "ALPHA-OUTAGE-0810",
                    "Where is the ALPHA-OUTAGE-0810 marker described?",
                )
            )

    strategies = ("fixed_window", "structure_aware")
    stats = []
    span_metrics = []
    hotpot_metrics = []

    base_docs = [d for d, _, _ in gold_docs]
    # Also include other synthetic text-ish files for chunk count comparison
    extra_docs: list[ParsedDocument] = []
    for name in ("incident_march.md", "change_log.html", "status_update.txt"):
        p = SYNTHETIC_DIR / name
        if p.exists():
            parsed = parse_document(p.name, p.read_bytes())
            extra_docs.append(
                ParsedDocument(
                    text=normalize_text(parsed.text),
                    title=parsed.title,
                    metadata=dict(parsed.metadata),
                    spans=list(parsed.spans),
                )
            )

    all_docs = base_docs + extra_docs
    hotpot_records: list[dict[str, Any]] = []
    if RAW_CORPUS.exists():
        for i, rec in enumerate(iter_jsonl(RAW_CORPUS)):
            if i >= args.hotpot_sample:
                break
            hotpot_records.append(rec)
            all_docs.append(
                _parsed_from_text(str(rec.get("title") or f"h{i}"), str(rec.get("text") or ""))
            )

    for strat in strategies:
        stats.append(
            chunk_stats(
                all_docs,
                strat,
                chunk_tokens=args.chunk_tokens,
                overlap_tokens=args.overlap_tokens,
            )
        )
        if gold_docs:
            span_metrics.append(
                span_recall_at_k(
                    gold_docs,
                    strat,
                    chunk_tokens=args.chunk_tokens,
                    overlap_tokens=args.overlap_tokens,
                    k=args.k,
                )
            )
        if hotpot_records:
            hotpot_metrics.append(
                retrieval_proxy_hotpot(
                    hotpot_records,
                    strat,
                    chunk_tokens=args.chunk_tokens,
                    overlap_tokens=args.overlap_tokens,
                    k=args.k,
                )
            )

    # Winner: prioritize gold span Recall@K then MRR; tie-break fewer chunks (efficiency)
    winner = "structure_aware"
    reason = "default preference for heading-aware boundaries"
    if span_metrics:
        best = max(
            span_metrics,
            key=lambda m: (m["recall_at_k"], m["mrr"], -next(
                s["total_chunks"] for s in stats if s["strategy"] == m["strategy"]
            )),
        )
        winner = best["strategy"]
        other = [m for m in span_metrics if m["strategy"] != winner]
        reason = (
            f"Higher span-level Recall@{args.k}={best['recall_at_k']} "
            f"and MRR={best['mrr']} on synthetic gold markers"
        )
        if other and other[0]["recall_at_k"] == best["recall_at_k"]:
            # tie on recall — prefer fewer chunks or structure
            w_stats = next(s for s in stats if s["strategy"] == winner)
            o_stats = next(s for s in stats if s["strategy"] == other[0]["strategy"])
            if w_stats["total_chunks"] <= o_stats["total_chunks"]:
                reason += (
                    f"; tie on recall, fewer/equal chunks "
                    f"({w_stats['total_chunks']} vs {o_stats['total_chunks']})"
                )
            else:
                reason += "; tie on recall, kept structure_aware for heading context"

    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "chunk_tokens": args.chunk_tokens,
        "overlap_tokens": args.overlap_tokens,
        "k": args.k,
        "chunk_stats": stats,
        "span_metrics_synthetic": span_metrics,
        "hotpot_proxy_metrics": hotpot_metrics,
        "winner": winner,
        "reason": reason,
        "doc_counts": {
            "synthetic_gold": len(gold_docs),
            "extra_synthetic": len(extra_docs),
            "hotpot_sample": len(hotpot_records),
            "total_chunked": len(all_docs),
        },
    }
    write_json(RESULTS_JSON, payload)

    md = [
        "# Chunking comparison (DOC-6)",
        "",
        f"Generated: {payload['created_at']}",
        "",
        f"**Winner:** `{winner}`",
        "",
        f"**Why:** {reason}",
        "",
        "## Chunk stats",
        "",
        "| Strategy | Docs | Chunks | Avg chunks/doc | Avg tokens | Latency s |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in stats:
        md.append(
            f"| {s['strategy']} | {s['documents']} | {s['total_chunks']} | "
            f"{s['avg_chunks_per_doc']} | {s['avg_chunk_tokens']} | {s['latency_seconds']} |"
        )
    md.extend(["", "## Span metrics (synthetic gold)", ""])
    if span_metrics:
        md.append("| Strategy | Recall@K | MRR |")
        md.append("| --- | ---: | ---: |")
        for m in span_metrics:
            md.append(f"| {m['strategy']} | {m['recall_at_k']} | {m['mrr']} |")
    else:
        md.append("_No gold spans available._")
    md.extend(["", "## Hotpot lexical proxy", ""])
    if hotpot_metrics:
        md.append("| Strategy | Recall@K | MRR |")
        md.append("| --- | ---: | ---: |")
        for m in hotpot_metrics:
            md.append(f"| {m['strategy']} | {m['recall_at_k']} | {m['mrr']} |")
    else:
        md.append("_No Hotpot sample._")
    md.append("")
    RESULTS_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"winner={winner} -> {RESULTS_JSON.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
