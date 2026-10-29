"""Pilot ingest N corpus records into Neon + Qdrant (real FastEmbed + BM25).

Usage:
  uv run python scripts/pilot_ingest.py
  uv run python scripts/pilot_ingest.py --limit 500
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from scripts._phase6_common import (  # noqa: E402
    EVIDENCE_DIR,
    RAW_CORPUS,
    build_store,
    ensure_dirs,
    estimate_from_pilot,
    ingest_records,
    iter_jsonl,
    neon_database_size_bytes,
    neon_doc_counts,
    qdrant_collection_stats,
    write_json,
)


def main() -> None:
    import logging

    parser = argparse.ArgumentParser(description="Pilot ingest into Neon+Qdrant")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--throttle", type=float, default=0.0)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=RAW_CORPUS,
        help="Path to corpus.jsonl",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    ensure_dirs()

    if not args.corpus.exists():
        print(
            f"ERROR: corpus missing at {args.corpus}. "
            "Run: uv run python scripts/build_corpus.py --limit 2000",
            file=sys.stderr,
        )
        sys.exit(1)

    records = list(iter_jsonl(args.corpus))
    batch = records[args.offset : args.offset + args.limit]
    if not batch:
        print("ERROR: empty batch", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    # Baseline sizes
    neon_before = neon_database_size_bytes(settings)
    counts_before = neon_doc_counts(settings)
    store = build_store(settings)
    q_before = qdrant_collection_stats(store)

    print(f"pilot ingest n={len(batch)} (offset={args.offset})", flush=True)
    print("measuring baselines + loading embedder...", flush=True)
    t0 = time.perf_counter()
    result = ingest_records(batch, settings=settings, throttle_s=args.throttle)
    wall = time.perf_counter() - t0

    neon_after = neon_database_size_bytes(settings)
    counts_after = neon_doc_counts(settings)
    q_after = qdrant_collection_stats(store)

    neon_delta = None
    if neon_before.get("size_bytes") is not None and neon_after.get("size_bytes") is not None:
        neon_delta = int(neon_after["size_bytes"]) - int(neon_before["size_bytes"])

    points_delta = None
    if q_before.get("points_count") is not None and q_after.get("points_count") is not None:
        points_delta = int(q_after["points_count"]) - int(q_before["points_count"])

    disk_est_after = q_after.get("estimated_disk_bytes_lower_bound")
    disk_est_before = q_before.get("estimated_disk_bytes_lower_bound")
    disk_delta = None
    if disk_est_after is not None and disk_est_before is not None:
        disk_delta = int(disk_est_after) - int(disk_est_before)

    docs_added = max(
        0,
        int(counts_after["active_documents"]) - int(counts_before["active_documents"]),
    )
    # Prefer outcome created+near_duplicate as successfully indexed
    outcomes = result.get("outcomes") or {}
    indexed = int(outcomes.get("created", 0)) + int(outcomes.get("near_duplicate", 0))
    if indexed == 0:
        indexed = docs_added or result["attempted"]

    estimate = estimate_from_pilot(
        pilot_docs=max(indexed, 1),
        pilot_neon_bytes=neon_delta if neon_delta and neon_delta > 0 else (
            int(neon_after["size_bytes"]) if neon_after.get("size_bytes") else None
        ),
        pilot_qdrant_points=points_delta if points_delta and points_delta > 0 else (
            int(q_after.get("points_count") or 0)
        ),
        pilot_estimated_qdrant_disk=disk_delta if disk_delta and disk_delta > 0 else (
            int(disk_est_after) if disk_est_after else None
        ),
        pilot_wall_s=wall,
        target_docs=55_000,
    )
    # If neon_delta is total DB size (not delta), scale from per-doc using delta preferred
    if neon_delta is not None and neon_delta > 0:
        estimate = estimate_from_pilot(
            pilot_docs=max(indexed, 1),
            pilot_neon_bytes=neon_delta,
            pilot_qdrant_points=max(points_delta or 0, 1),
            pilot_estimated_qdrant_disk=disk_delta or disk_est_after,
            pilot_wall_s=wall,
            target_docs=55_000,
        )

    evidence: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "limit": args.limit,
        "offset": args.offset,
        "attempted": result["attempted"],
        "outcomes": outcomes,
        "errors_sample": result.get("errors_sample"),
        "wall_seconds": round(wall, 3),
        "records_per_second": round(len(batch) / wall, 3) if wall > 0 else None,
        "neon_before": neon_before,
        "neon_after": neon_after,
        "neon_delta_bytes": neon_delta,
        "counts_before": counts_before,
        "counts_after": counts_after,
        "qdrant_before": q_before,
        "qdrant_after": q_after,
        "qdrant_points_delta": points_delta,
        "qdrant_disk_estimate_delta_bytes": disk_delta,
        "indexed_proxy": indexed,
        "storage_estimate_55k_preview": estimate,
        "notes": [
            "Secrets not logged.",
            "Qdrant disk/ram API fields may be unavailable on Free; "
            "estimated_disk_bytes_lower_bound is a planning lower bound.",
        ],
    }
    out_path = EVIDENCE_DIR / "pilot_ingest.json"
    write_json(out_path, evidence)
    # Also write estimate file (task 4) from pilot
    write_json(EVIDENCE_DIR / "storage_estimate_55k.json", estimate)

    print(
        f"pilot done attempted={result['attempted']} wall_s={wall:.1f} "
        f"rps={evidence['records_per_second']} "
        f"neon_delta_bytes={neon_delta} qdrant_points_delta={points_delta}"
    )
    print(
        f"55k go={estimate['full_ingest_go']} "
        f"proposed_max_safe={estimate['proposed_max_safe_docs']} "
        f"-> {out_path.relative_to(ROOT).as_posix()}"
    )


if __name__ == "__main__":
    main()
