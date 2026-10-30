"""Verify Postgres vs Qdrant counts → docs/evidence/dataset_counts.json."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from scripts._phase6_common import (  # noqa: E402
    EVIDENCE_DIR,
    build_store,
    ensure_dirs,
    neon_database_size_bytes,
    neon_doc_counts,
    qdrant_collection_stats,
    write_json,
)
from sqlalchemy import text  # noqa: E402


def _chunk_rows_by_doc_status(settings: Settings) -> tuple[int | None, int | None]:
    """Return (ACTIVE chunk rows, DELETED chunk rows) when Postgres is available."""
    try:
        engine = get_engine(settings.database_url)
        with engine.connect() as conn:
            rows = {
                str(status): int(n)
                for status, n in conn.execute(
                    text(
                        """
                        SELECT d.status, count(c.id)
                        FROM chunks c
                        JOIN documents d ON d.id = c.document_id
                        GROUP BY d.status
                        """
                    )
                ).all()
            }
        return int(rows.get("ACTIVE", 0)), int(rows.get("DELETED", 0))
    except Exception:  # noqa: BLE001
        return None, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify dataset counts")
    parser.parse_args()
    ensure_dirs()
    settings = get_settings()
    counts = neon_doc_counts(settings)
    neon = neon_database_size_bytes(settings)
    store = build_store(settings)
    qstats = qdrant_collection_stats(store)

    active = counts["active_documents"]
    points = int(qstats.get("points_count") or 0)
    # Consistency: points should be >= active (multi-chunk); warn if points==0 and active>0
    consistent = True
    notes: list[str] = []
    if active > 0 and points == 0:
        consistent = False
        notes.append("ACTIVE docs > 0 but Qdrant points == 0")
    if points > 0 and active == 0:
        consistent = False
        notes.append("Qdrant points > 0 but ACTIVE docs == 0")
    # Soft check: chunks roughly match points for active versions (not exact across versions)
    chunk_rows = counts["chunk_rows"]
    active_chunk_rows, deleted_chunk_rows = _chunk_rows_by_doc_status(settings)
    if points and active_chunk_rows and points != active_chunk_rows:
        notes.append(
            f"ACTIVE chunk rows ({active_chunk_rows}) != Qdrant points ({points})"
        )
        if abs(points - active_chunk_rows) > max(50, int(0.25 * max(active_chunk_rows, 1))):
            consistent = False
    if chunk_rows and active_chunk_rows is not None and deleted_chunk_rows is not None:
        gap = chunk_rows - points
        if gap == deleted_chunk_rows and points == active_chunk_rows:
            notes.append(
                f"total chunk_rows ({chunk_rows}) - qdrant_points ({points}) = "
                f"{gap} equals DELETED-document chunk rows "
                f"({deleted_chunk_rows}); ACTIVE chunks match Qdrant exactly"
            )
        elif points and chunk_rows and abs(points - chunk_rows) > max(
            50, int(0.25 * chunk_rows)
        ):
            notes.append(
                f"soft mismatch: qdrant_points={points} vs chunk_rows={chunk_rows} "
                "(may include DELETED or old versions in Postgres)"
            )

    payload: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "postgres": {
            **counts,
            "active_chunk_rows": active_chunk_rows,
            "deleted_chunk_rows": deleted_chunk_rows,
        },
        "neon_size": neon,
        "qdrant": qstats,
        "consistency": {
            "ok": consistent,
            "active_documents": active,
            "active_chunk_rows": active_chunk_rows,
            "deleted_chunk_rows": deleted_chunk_rows,
            "qdrant_points": points,
            "notes": notes,
        },
        "claims": {
            "do_not_claim_50k_without_measurement": True,
            "measured_active_documents": active,
            "measured_qdrant_points": points,
            "meets_data1_50k": active >= 50_000,
        },
    }
    out = EVIDENCE_DIR / "dataset_counts.json"
    write_json(out, payload)
    print(
        f"active_docs={active} qdrant_points={points} consistent={consistent} "
        f"meets_50k={active >= 50_000} -> {out.relative_to(ROOT).as_posix()}"
    )


if __name__ == "__main__":
    main()
