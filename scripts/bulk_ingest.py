"""Resumable bulk ingest toward ≥50k (or max safe). Respects storage estimate.

Usage:
  uv run python scripts/bulk_ingest.py --max-docs 50000
  uv run python scripts/bulk_ingest.py --max-docs 5000 --throttle 0.01
"""

from __future__ import annotations

import argparse
import contextlib
import json
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
    DATA_DIR,
    EVIDENCE_DIR,
    RAW_CORPUS,
    ensure_dirs,
    ingest_records,
    iter_jsonl,
    neon_database_size_bytes,
    neon_doc_counts,
    write_json,
)

CHECKPOINT = DATA_DIR / "checkpoints" / "bulk_ingest.json"
LOCK_PATH = DATA_DIR / "checkpoints" / "bulk_ingest.lock"
ESTIMATE_PATH = EVIDENCE_DIR / "storage_estimate_55k.json"


def load_estimate() -> dict[str, Any] | None:
    if not ESTIMATE_PATH.exists():
        return None
    return json.loads(ESTIMATE_PATH.read_text(encoding="utf-8"))


def _acquire_lock() -> Any:
    """Exclusive lock so only one bulk_ingest process runs (prevents UniqueViolation races)."""
    import os

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = LOCK_PATH.open("a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            fh.write("0")
            fh.flush()
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.close()
        raise SystemExit(
            "ERROR: another bulk_ingest.py holds the lock "
            f"({LOCK_PATH}). Kill duplicates before retrying."
        ) from exc
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable bulk corpus ingest")
    parser.add_argument("--max-docs", type=int, default=50_000)
    parser.add_argument("--throttle", type=float, default=0.0)
    parser.add_argument("--checkpoint-every", type=int, default=50)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Docs per embed/upsert batch (1 = legacy per-doc path)",
    )
    parser.add_argument("--force", action="store_true", help="Ignore no-go estimate")
    parser.add_argument("--reset-checkpoint", action="store_true")
    parser.add_argument(
        "--check-near-dup",
        action="store_true",
        help="Enable SimHash near-dup checks (slower; forces batch_size=1)",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=None,
        help="Inclusive start within the capped corpus (for parallel shards)",
    )
    parser.add_argument(
        "--end-index",
        type=int,
        default=None,
        help="Exclusive end within the capped corpus (for parallel shards)",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Checkpoint JSON path (default data/checkpoints/bulk_ingest.json)",
    )
    parser.add_argument(
        "--evidence-out",
        type=Path,
        default=None,
        help="Evidence JSON path (default docs/evidence/bulk_ingest.json)",
    )
    args = parser.parse_args()
    import logging

    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ensure_dirs()
    lock_fh = _acquire_lock()

    estimate = load_estimate()
    if estimate is None:
        print(
            "ERROR: missing storage_estimate_55k.json — run pilot_ingest.py first",
            file=sys.stderr,
        )
        sys.exit(1)

    max_docs = args.max_docs
    proposed = int(estimate.get("proposed_max_safe_docs") or max_docs)
    go = bool(estimate.get("full_ingest_go"))
    if not go and not args.force:
        max_docs = min(max_docs, proposed)
        print(
            f"NOTE: estimate full_ingest_go=false; capping max_docs={max_docs} "
            f"(proposed_max_safe={proposed}). Use --force to override.",
            file=sys.stderr,
        )
    elif go:
        print(f"estimate go=true; targeting max_docs={max_docs}")

    if not RAW_CORPUS.exists():
        print("ERROR: corpus.jsonl missing", file=sys.stderr)
        sys.exit(1)

    all_records = list(iter_jsonl(RAW_CORPUS))[:max_docs]
    if len(all_records) < max_docs:
        print(
            f"NOTE: corpus only has {len(all_records)} records (requested {max_docs})",
            file=sys.stderr,
        )

    start = 0 if args.start_index is None else max(0, args.start_index)
    end = len(all_records) if args.end_index is None else min(len(all_records), args.end_index)
    if start > end:
        print(f"ERROR: start-index {start} > end-index {end}", file=sys.stderr)
        sys.exit(1)
    records = all_records[start:end]
    print(f"shard window corpus[{start}:{end}] n={len(records)}", flush=True)

    checkpoint = args.checkpoint or CHECKPOINT
    if args.reset_checkpoint and checkpoint.exists():
        checkpoint.unlink()
    start_index = 0
    if checkpoint.exists():
        ck = json.loads(checkpoint.read_text(encoding="utf-8"))
        start_index = int(ck.get("next_index") or 0)
        print(f"resuming from checkpoint next_index={start_index}")

    settings = get_settings()
    t0 = time.perf_counter()
    batch_size = 1 if args.check_near_dup else max(1, args.batch_size)
    result = ingest_records(
        records,
        settings=settings,
        throttle_s=args.throttle,
        checkpoint_path=checkpoint,
        checkpoint_every=args.checkpoint_every,
        start_index=start_index,
        check_near_duplicates=args.check_near_dup,
        batch_size=batch_size,
    )
    wall = time.perf_counter() - t0
    counts = neon_doc_counts(settings)
    neon = neon_database_size_bytes(settings)

    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "max_docs_requested": args.max_docs,
        "max_docs_effective": len(all_records),
        "shard_start": start,
        "shard_end": end,
        "full_ingest_go": go,
        "forced": args.force,
        "estimate_proposed_max_safe": proposed,
        "result": result,
        "wall_seconds_this_run": round(wall, 3),
        "neon_counts": counts,
        "neon_size": neon,
        "checkpoint": str(checkpoint.relative_to(ROOT)).replace("\\", "/")
        if checkpoint.is_relative_to(ROOT)
        else str(checkpoint),
    }
    out = args.evidence_out or (EVIDENCE_DIR / "bulk_ingest.json")
    write_json(out, summary)
    print(
        f"bulk done processed={result['attempted']} "
        f"outcomes={result['outcomes']} active={counts['active_documents']} "
        f"-> {out.as_posix()}"
    )
    with contextlib.suppress(Exception):
        lock_fh.close()


if __name__ == "__main__":
    main()
