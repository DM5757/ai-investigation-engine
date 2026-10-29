"""Build HotpotQA distractor corpus → data/raw/corpus.jsonl + manifest.

Usage:
  uv run python scripts/build_corpus.py --limit 2000
  uv run python scripts/build_corpus.py --target 55000

If Hugging Face download fails, falls back to data/samples/hotpot_sample.jsonl
and writes HUMAN ACTION notes into the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._phase6_common import (  # noqa: E402
    CORPUS_MANIFEST,
    RAW_CORPUS,
    SAMPLE_CORPUS,
    ensure_dirs,
    write_json,
)

DEFAULT_SEED = 42
DEFAULT_TARGET = 55_000


def _stable_title_key(title: str) -> str:
    cleaned = " ".join(title.strip().split())
    return f"hotpotqa:{cleaned}"


def _paragraph_from_context_item(item: Any) -> tuple[str, str] | None:
    """Hotpot context item is typically [title, [sent1, sent2, ...]]."""
    if not isinstance(item, (list, tuple)) or len(item) < 2:
        return None
    title = str(item[0]).strip()
    sents = item[1]
    if isinstance(sents, str):
        text = sents.strip()
    elif isinstance(sents, (list, tuple)):
        text = " ".join(str(s).strip() for s in sents if str(s).strip())
    else:
        return None
    if not title or not text:
        return None
    return title, text


def extract_unique_paragraphs(
    examples: Any,
    *,
    seed: int,
    limit: int | None,
    progress_every: int = 5_000,
) -> list[dict[str, Any]]:
    """Dedup by title; deterministic shuffle after insertion-order collect.

    Streams examples so parquet loaders need not materialize the full split in RAM.
    When ``limit`` is set we still scan all examples first (for a stable shuffle pool),
    unless the caller already capped the iterator.
    """
    by_key: dict[str, dict[str, Any]] = {}
    n_examples = 0
    for ex in examples:
        n_examples += 1
        if progress_every and n_examples % progress_every == 0:
            print(
                f"extract progress examples={n_examples} unique_titles={len(by_key)}",
                flush=True,
            )
        context = ex.get("context") if isinstance(ex, dict) else None
        # datasets row may be dict-like
        if context is None and hasattr(ex, "get"):
            context = ex.get("context")
        if context is None:
            continue
        # HF distractor: context may be {"title": [...], "sentences": [...]} or list of pairs
        items: list[Any]
        if isinstance(context, dict) and "title" in context and "sentences" in context:
            titles = context["title"]
            sentences = context["sentences"]
            items = list(zip(titles, sentences, strict=False))
        elif isinstance(context, (list, tuple)):
            items = list(context)
        else:
            continue
        for item in items:
            parsed = _paragraph_from_context_item(item)
            if parsed is None:
                continue
            title, text = parsed
            key = _stable_title_key(title)
            if key in by_key:
                continue
            by_key[key] = {
                "id": key,
                "title": title,
                "text": text,
                "meta": {
                    "source": "hotpotqa",
                    "config": "distractor",
                    "license": "CC-BY-SA-4.0",
                },
            }

    print(
        f"extract done examples={n_examples} unique_titles={len(by_key)}",
        flush=True,
    )
    records = list(by_key.values())
    rng = random.Random(seed)
    rng.shuffle(records)
    if limit is not None:
        records = records[:limit]
    return records


def _write_sample_fallback(n: int = 800) -> list[dict[str, Any]]:
    """Deterministic synthetic Hotpot-like paragraphs for offline pilot."""
    ensure_dirs()
    rng = random.Random(DEFAULT_SEED)
    topics = [
        "PaymentService",
        "AuthGateway",
        "LedgerWorker",
        "NotifyBus",
        "BillingAPI",
        "FraudScorer",
        "CardVault",
        "SettlementBatch",
    ]
    records: list[dict[str, Any]] = []
    for i in range(n):
        topic = topics[i % len(topics)]
        title = f"Sample Article {topic} {i}"
        text = (
            f"{title} is a Wikipedia-style paragraph used as an offline HotpotQA stand-in. "
            f"It discusses {topic} reliability after a March configuration change. "
            f"Operators observed latency spikes of {50 + (i % 40)} ms and retries. "
            f"Related systems include {topics[(i + 1) % len(topics)]} and "
            f"{topics[(i + 3) % len(topics)]}. Seed token {rng.randint(1000, 9999)}."
        )
        key = _stable_title_key(title)
        records.append(
            {
                "id": key,
                "title": title,
                "text": text,
                "meta": {
                    "source": "offline_sample",
                    "config": "distractor_standin",
                    "license": "internal-sample",
                    "warning": "Not real HotpotQA; HF download failed or --offline",
                },
            }
        )
    SAMPLE_CORPUS.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE_CORPUS.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return records


# Hugging Face parquet files (prefer over curtis.ml.cmu.edu / datasets+pandas).
_HF_PARQUET: dict[str, list[str]] = {
    "train": [
        "distractor/train-00000-of-00002.parquet",
        "distractor/train-00001-of-00002.parquet",
    ],
    "validation": ["distractor/validation-00000-of-00001.parquet"],
    "dev": ["distractor/validation-00000-of-00001.parquet"],
}

_CMU_JSON: dict[str, str] = {
    "train": "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_train_v1.1.json",
    "validation": "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json",
    "dev": "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json",
}


def _row_from_parquet_batch(batch: Any) -> list[dict[str, Any]]:
    """Convert a pyarrow RecordBatch / table slice to Hotpot-like dicts."""
    cols = {name: batch.column(name) for name in batch.column_names}
    n = batch.num_rows
    out: list[dict[str, Any]] = []
    for i in range(n):
        row: dict[str, Any] = {}
        for name, col in cols.items():
            row[name] = col[i].as_py()
        out.append(row)
    return out


def _ensure_hf_parquet_cached(splits: list[str]) -> tuple[list[Path], dict[str, Any]]:
    """Download Hotpot distractor parquet shards to cache; return local paths + info."""
    import httpx

    cache_dir = ROOT / "data" / "cache" / "hotpot_hf"
    cache_dir.mkdir(parents=True, exist_ok=True)
    base = "https://huggingface.co/datasets/hotpotqa/hotpot_qa/resolve/main/"
    info: dict[str, Any] = {
        "method": "hf_parquet_pyarrow_stream",
        "splits_loaded": [],
        "rows": 0,
        "files": [],
    }
    paths: list[Path] = []
    timeout = httpx.Timeout(600.0, connect=60.0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for split in splits:
            rels = _HF_PARQUET.get(split)
            if not rels:
                raise ValueError(f"unknown split {split!r}")
            split_rows = 0
            for rel in rels:
                name = Path(rel).name
                cache_path = cache_dir / name
                if not cache_path.exists() or cache_path.stat().st_size < 1000:
                    url = base + rel
                    print(f"downloading {rel} ...", flush=True)
                    resp = client.get(url)
                    resp.raise_for_status()
                    cache_path.write_bytes(resp.content)
                    source = "download"
                else:
                    source = "cache"
                    print(f"cache hit {name}", flush=True)
                # Row count from metadata only (no full decode yet).
                import pyarrow.parquet as pq

                meta_rows = int(pq.ParquetFile(cache_path).metadata.num_rows)
                split_rows += meta_rows
                info["files"].append(
                    {"path": rel, "rows": meta_rows, "source": source}
                )
                paths.append(cache_path)
            info["splits_loaded"].append({"split": split, "rows": split_rows})
            info["rows"] += split_rows
    return paths, info


def _iter_hotpot_parquet_examples(paths: list[Path], *, batch_size: int = 256) -> Any:
    """Yield Hotpot row dicts from parquet without loading whole shards into RAM."""
    import pyarrow.parquet as pq

    for path in paths:
        print(f"streaming {path.name} ...", flush=True)
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=batch_size, columns=["context"]):
            yield from _row_from_parquet_batch(batch)


def _load_hotpot_hf_parquet(splits: list[str]) -> tuple[Any, dict[str, Any]]:
    """Stream distractor parquet from HF cache via pyarrow (no pandas / datasets)."""
    paths, info = _ensure_hf_parquet_cached(splits)
    # Return a lazy iterator; extract_unique_paragraphs consumes it once.
    return _iter_hotpot_parquet_examples(paths), info


def _load_hotpot_cmu_json(splits: list[str]) -> tuple[list[Any], dict[str, Any]]:
    """Download official HotpotQA JSON from CMU (may be DNS-blocked)."""
    import httpx

    cache_dir = ROOT / "data" / "cache" / "hotpot"
    cache_dir.mkdir(parents=True, exist_ok=True)
    info: dict[str, Any] = {"method": "cmu_json", "splits_loaded": [], "rows": 0}
    examples: list[Any] = []
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=60.0), follow_redirects=True) as client:
        for split in splits:
            url = _CMU_JSON.get(split)
            if url is None:
                raise ValueError(f"unknown split {split!r}")
            cache_path = cache_dir / f"{split}.json"
            if cache_path.exists() and cache_path.stat().st_size > 1000:
                raw = cache_path.read_bytes()
                source = "cache"
            else:
                resp = client.get(url)
                resp.raise_for_status()
                raw = resp.content
                cache_path.write_bytes(raw)
                source = "download"
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, list):
                raise RuntimeError(f"expected list JSON for {split}")
            examples.extend(data)
            info["splits_loaded"].append(
                {"split": split, "rows": len(data), "source": source, "url": url}
            )
            info["rows"] += len(data)
    return examples, info


def _load_hotpot_datasets(splits: list[str]) -> tuple[list[Any], dict[str, Any]]:
    """Optional Hugging Face datasets fallback (may fail if pandas DLL blocked)."""
    try:
        from datasets import load_dataset
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"datasets import failed: {exc}") from exc
    info: dict[str, Any] = {"method": "huggingface_datasets", "splits_loaded": [], "rows": 0}
    examples: list[Any] = []
    for split in splits:
        hf_split = "validation" if split in {"dev", "validation"} else split
        ds = load_dataset("hotpotqa/hotpot_qa", "distractor", split=hf_split)
        examples.extend(list(ds))
        info["splits_loaded"].append({"split": hf_split, "rows": len(ds)})
        info["rows"] += len(ds)
    return examples, info


def load_hotpot_examples(*, splits: list[str]) -> tuple[list[Any], dict[str, Any]]:
    """Load HotpotQA distractor: HF parquet+pyarrow, then CMU JSON, then datasets."""
    errors: list[str] = []
    for loader, label in (
        (_load_hotpot_hf_parquet, "hf_parquet"),
        (_load_hotpot_cmu_json, "cmu_json"),
        (_load_hotpot_datasets, "datasets"),
    ):
        try:
            return loader(splits)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
    raise RuntimeError("HotpotQA load failed: " + " | ".join(errors))


def write_corpus(
    records: list[dict[str, Any]],
    *,
    seed: int,
    source_mode: str,
    human_action: str | None,
    load_info: dict[str, Any] | None,
) -> dict[str, Any]:
    ensure_dirs()
    RAW_CORPUS.parent.mkdir(parents=True, exist_ok=True)
    with RAW_CORPUS.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    digest = hashlib.sha256()
    with RAW_CORPUS.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)

    manifest: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "record_count": len(records),
        "unique_ids": True,
        "id_scheme": "hotpotqa:<title>",
        "output": str(RAW_CORPUS.relative_to(ROOT)).replace("\\", "/"),
        "sha256": digest.hexdigest(),
        "source_mode": source_mode,
        "target_capability": DEFAULT_TARGET,
        "license_note": "HotpotQA CC BY-SA 4.0 — attribute authors; share-alike derivatives",
        "load_info": load_info,
        "human_action": human_action,
        "meets_55k_capability": len(records) >= DEFAULT_TARGET,
    }
    write_json(CORPUS_MANIFEST, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HotpotQA distractor corpus JSONL")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap unique paragraphs (pilot). Omit for full target.",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=DEFAULT_TARGET,
        help="Desired unique count when --limit omitted (default 55000)",
    )
    parser.add_argument(
        "--splits",
        default="train,validation",
        help="Comma-separated Hotpot splits",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip HF; use/create offline sample only",
    )
    args = parser.parse_args()

    ensure_dirs()
    limit = args.limit
    if limit is None:
        limit = args.target

    human_action: str | None = None
    load_info: dict[str, Any] | None = None
    source_mode = "huggingface"

    if args.offline:
        records = _write_sample_fallback(max(limit, 800))
        records = records[:limit]
        source_mode = "offline_sample"
        human_action = (
            "HUMAN ACTION: Ran with --offline. To build real HotpotQA corpus: "
            "`uv sync --group dev` then `uv run python scripts/build_corpus.py "
            "--target 55000` with network access to huggingface.co."
        )
    else:
        try:
            splits = [s.strip() for s in args.splits.split(",") if s.strip()]
            examples, load_info = load_hotpot_examples(splits=splits)
            records = extract_unique_paragraphs(examples, seed=args.seed, limit=limit)
            if len(records) < min(limit, 100):
                raise RuntimeError(f"too few unique paragraphs extracted: {len(records)}")
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: HotpotQA download/extract failed: {exc}", file=sys.stderr)
            records = _write_sample_fallback(max(limit, 800))
            records = records[:limit]
            source_mode = "offline_sample_fallback"
            human_action = (
                "HUMAN ACTION: Hugging Face HotpotQA download failed. "
                f"Error: {exc!s}. Installed offline sample at "
                f"{SAMPLE_CORPUS.as_posix()}. Re-run with network + "
                "`uv sync --group dev` then "
                "`uv run python scripts/build_corpus.py --target 55000`."
            )

    manifest = write_corpus(
        records,
        seed=args.seed,
        source_mode=source_mode,
        human_action=human_action,
        load_info=load_info,
    )
    print(
        f"wrote {manifest['record_count']} records -> {manifest['output']} "
        f"mode={source_mode} sha256={manifest['sha256'][:12]}..."
    )
    if human_action:
        print(human_action, file=sys.stderr)
    if not manifest["meets_55k_capability"]:
        print(
            f"NOTE: corpus has {manifest['record_count']} records "
            f"(< {DEFAULT_TARGET}). Re-run without small --limit for full build.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
