"""CRC32 collision analysis on BM25 term vocabulary → evidence JSON.

Usage:
  uv run python scripts/crc32_collision_analysis.py
  uv run python scripts/crc32_collision_analysis.py --max-chunks 20000
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.retrieval.bm25_sparse import term_id  # noqa: E402
from app.retrieval.tokenizer import tokenize  # noqa: E402
from scripts._phase6_common import (  # noqa: E402
    EVIDENCE_DIR,
    RAW_CORPUS,
    ensure_dirs,
    iter_jsonl,
    write_json,
)


def analyze_terms(terms: set[str]) -> dict[str, Any]:
    buckets: dict[int, list[str]] = defaultdict(list)
    for term in terms:
        buckets[term_id(term)].append(term)
    collisions = {f"{k:08x}": sorted(v) for k, v in buckets.items() if len(v) > 1}
    n_terms = len(terms)
    n_ids = len(buckets)
    n_collision_ids = len(collisions)
    n_terms_in_collisions = sum(len(v) for v in collisions.values())
    return {
        "unique_terms": n_terms,
        "unique_crc32_ids": n_ids,
        "collision_id_count": n_collision_ids,
        "terms_involved_in_collisions": n_terms_in_collisions,
        "collision_rate_ids": round(n_collision_ids / n_ids, 8) if n_ids else 0.0,
        "collision_rate_terms": (
            round(n_terms_in_collisions / n_terms, 8) if n_terms else 0.0
        ),
        "sample_collisions": dict(list(sorted(collisions.items()))[:25]),
        "assessment": (
            "negligible"
            if n_collision_ids == 0
            else (
                "low"
                if n_collision_ids / max(n_ids, 1) < 1e-4
                else "review"
            )
        ),
    }


def collect_from_db(*, max_chunks: int) -> set[str]:
    settings = get_settings()
    engine = get_engine(settings.database_url)
    sql = """
        SELECT c.text FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'ACTIVE' AND c.version = d.active_version
        ORDER BY c.id
        LIMIT :lim
    """
    terms: set[str] = set()
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"lim": max_chunks}).fetchall()
    for (txt,) in rows:
        terms.update(tokenize(str(txt or "")))
    return terms


def collect_from_corpus(*, max_docs: int) -> set[str]:
    terms: set[str] = set()
    if not RAW_CORPUS.exists():
        return terms
    for i, rec in enumerate(iter_jsonl(RAW_CORPUS)):
        if i >= max_docs:
            break
        terms.update(tokenize(str(rec.get("text") or "")))
    return terms


def main() -> None:
    parser = argparse.ArgumentParser(description="CRC32 term-id collision analysis")
    parser.add_argument("--max-chunks", type=int, default=20_000)
    parser.add_argument("--max-corpus-docs", type=int, default=20_000)
    args = parser.parse_args()
    ensure_dirs()

    db_terms = collect_from_db(max_chunks=args.max_chunks)
    corpus_terms = collect_from_corpus(max_docs=args.max_corpus_docs)
    all_terms = db_terms | corpus_terms
    analysis = analyze_terms(all_terms)
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "sources": {
            "db_terms": len(db_terms),
            "corpus_terms": len(corpus_terms),
            "union_terms": len(all_terms),
            "max_chunks": args.max_chunks,
            "max_corpus_docs": args.max_corpus_docs,
        },
        "hash": "zlib.crc32 UTF-8 & 0xFFFFFFFF",
        **analysis,
        "note": (
            "Colliding terms share a sparse index dimension; BM25 weights sum. "
            "Low rates are acceptable for this assignment-scale vocab."
        ),
    }
    out = EVIDENCE_DIR / "crc32_collisions.json"
    write_json(out, payload)
    print(
        f"terms={analysis['unique_terms']} collision_ids={analysis['collision_id_count']} "
        f"assessment={analysis['assessment']} -> {out.relative_to(ROOT).as_posix()}"
    )


if __name__ == "__main__":
    main()
