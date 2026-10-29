"""Ingest data/synthetic/* into Neon + Qdrant via DocumentLifecycle (real parsers).

Usage:
  uv run python scripts/ingest_synthetic.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.ingestion.parsers.base import ParsedDocument, single_span  # noqa: E402
from app.ingestion.parsers.jsonl import JsonlParser  # noqa: E402
from app.ingestion.pipeline import prepare_document  # noqa: E402
from scripts._phase6_common import (  # noqa: E402
    EVIDENCE_DIR,
    SYNTHETIC_DIR,
    build_store,
    ensure_dirs,
    make_lifecycle,
    neon_doc_counts,
    open_session,
    write_json,
)


def _prepared_from_jsonl(
    path: Path,
    data: bytes,
    *,
    chunk_strategy: str,
    chunk_tokens: int,
    overlap_tokens: int,
):
    records = JsonlParser().parse_records(data, filename=path.name)
    joined = "\n\n".join(f"## {r.title}\n{r.text}" for r in records)
    parsed = ParsedDocument(
        text=joined,
        title=path.stem,
        metadata={
            "source_type": "jsonl",
            "origin": "synthetic",
            "record_count": len(records),
        },
        spans=single_span(joined),
    )

    def _parse(_filename: str, _data: bytes, doc: ParsedDocument = parsed) -> ParsedDocument:
        return doc

    return prepare_document(
        path.name,
        b"",
        chunk_strategy=chunk_strategy,
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
        parse_fn=_parse,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest synthetic enterprise files")
    parser.add_argument(
        "--dir",
        type=Path,
        default=SYNTHETIC_DIR,
        help="Directory of synthetic files",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ensure_dirs()

    if not args.dir.is_dir():
        print(f"ERROR: missing {args.dir}", file=sys.stderr)
        sys.exit(1)

    files = sorted(p for p in args.dir.iterdir() if p.is_file())
    if not files:
        print(f"ERROR: no files in {args.dir}", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    store = build_store(settings)
    session = open_session(settings)
    lifecycle = make_lifecycle(session, store, settings, check_near_duplicates=True)
    outcomes: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    try:
        for path in files:
            ext_key = f"synthetic:{path.name}"
            try:
                data = path.read_bytes()
                # Multi-record JSONL is one logical corpus file for Phase 6; join texts.
                if path.suffix.lower() == ".jsonl":
                    prep = _prepared_from_jsonl(
                        path,
                        data,
                        chunk_strategy=settings.chunk_strategy,
                        chunk_tokens=settings.chunk_tokens,
                        overlap_tokens=settings.overlap_tokens,
                    )
                    result = lifecycle.add(
                        path.name, b"", external_key=ext_key, prepared=prep
                    )
                else:
                    result = lifecycle.add(path.name, data, external_key=ext_key)
                key = str(result.outcome)
                outcomes[key] = outcomes.get(key, 0) + 1
                if key == "failed":
                    errors.append(
                        {"file": path.name, "error": (result.message or "")[:300]}
                    )
                print(f"{path.name} -> {key}", flush=True)
            except Exception as exc:  # noqa: BLE001
                outcomes["error"] = outcomes.get("error", 0) + 1
                errors.append({"file": path.name, "error": str(exc)[:300]})
                session.rollback()
                print(f"{path.name} -> error {exc}", flush=True)
    finally:
        session.close()

    counts = neon_doc_counts(settings)
    payload: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "files": [p.name for p in files],
        "outcomes": outcomes,
        "errors": errors,
        "neon_counts": counts,
    }
    out = EVIDENCE_DIR / "synthetic_ingest.json"
    write_json(out, payload)
    print(f"synthetic ingest done outcomes={outcomes} -> {out.as_posix()}")


if __name__ == "__main__":
    main()
