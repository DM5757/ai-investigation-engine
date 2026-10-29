"""Compute BM25 avgdl from real chunk texts; update index_stats + evidence.

Usage:
  uv run python scripts/compute_bm25_stats.py
  uv run python scripts/compute_bm25_stats.py --sample 5000
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db.repositories.documents import DocumentRepository  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.index.qdrant_store import collection_name  # noqa: E402
from app.retrieval.tokenizer import tokenize  # noqa: E402
from scripts._phase6_common import EVIDENCE_DIR, ensure_dirs, open_session, write_json  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute BM25 corpus avgdl")
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="If >0, sample at most N active-version chunks",
    )
    args = parser.parse_args()
    ensure_dirs()
    settings = get_settings()
    engine = get_engine(settings.database_url)

    sql = """
        SELECT c.text
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'ACTIVE' AND c.version = d.active_version
    """
    if args.sample > 0:
        # Deterministic-ish sample via ORDER BY id LIMIT (Postgres + SQLite)
        sql += " ORDER BY c.id LIMIT :lim"
        params: dict[str, Any] = {"lim": args.sample}
    else:
        params = {}

    lengths: list[int] = []
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    for (txt,) in rows:
        tokens = tokenize(str(txt or ""))
        lengths.append(len(tokens))

    if not lengths:
        avgdl = float(settings.bm25_avgdl)
        note = "no active chunks; leaving prior avgdl"
    else:
        avgdl = sum(lengths) / len(lengths)
        note = "computed from BM25 tokenizer token counts on active chunks"

    coll = collection_name(settings.chunk_strategy, settings.embedding_model_short)
    session = open_session(settings)
    try:
        repo = DocumentRepository(session)
        # Preserve existing counts if present
        existing = session.execute(
            text(
                "SELECT document_count, chunk_count FROM index_stats "
                "WHERE collection_name = :c"
            ),
            {"c": coll},
        ).fetchone()
        doc_count = int(existing[0]) if existing else 0
        chunk_count = int(existing[1]) if existing else len(lengths)
        if not existing:
            counts = session.execute(
                text("SELECT count(*) FROM documents WHERE status = 'ACTIVE'")
            ).scalar()
            doc_count = int(counts or 0)
            chunk_count = len(lengths)
        repo.upsert_index_stats(
            coll,
            document_count=doc_count,
            chunk_count=chunk_count,
            metadata={
                "bm25_avgdl": avgdl,
                "bm25_k1": settings.bm25_k1,
                "bm25_b": settings.bm25_b,
                "bm25_sample_chunks": len(lengths),
                "bm25_updated_at": datetime.now(UTC).isoformat(),
            },
        )
        session.commit()
    finally:
        session.close()

    lengths_sorted = sorted(lengths)
    p50 = lengths_sorted[len(lengths_sorted) // 2] if lengths_sorted else None
    evidence = {
        "created_at": datetime.now(UTC).isoformat(),
        "collection_name": coll,
        "chunk_count_sampled": len(lengths),
        "avgdl": round(avgdl, 4),
        "min_dl": min(lengths) if lengths else None,
        "max_dl": max(lengths) if lengths else None,
        "p50_dl": p50,
        "prior_settings_bm25_avgdl": settings.bm25_avgdl,
        "note": note,
        "recommendation": (
            f"Set BM25_AVGDL={avgdl:.2f} in environment and restart app "
            "so sparse encoding uses calibrated avgdl."
        ),
    }
    out = EVIDENCE_DIR / "bm25_corpus_stats.json"
    write_json(out, evidence)
    print(
        f"avgdl={avgdl:.4f} chunks={len(lengths)} collection={coll} "
        f"-> {out.relative_to(ROOT).as_posix()}"
    )
    print(evidence["recommendation"])


if __name__ == "__main__":
    main()
