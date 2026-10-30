# Phase 6 notes — Corpus scale + DOC-6 chunking

## Key modules

1. `scripts/build_corpus.py` — HotpotQA distractor → unique `hotpotqa:<title>` JSONL (HF parquet + pyarrow; CMU/datasets fallbacks).
2. `scripts/generate_synthetic.py` — multi-format enterprise docs + `synthetic_truth.json` (contradictions, injection, gold spans).
3. `scripts/pilot_ingest.py` / `bulk_ingest.py` — `DocumentLifecycle` + FastEmbed + BM25 → Neon + Qdrant Cloud; checkpointed bulk.
4. `scripts/_phase6_common.py` — size probes, 55k estimate, shared ingest.
5. `scripts/verify_counts.py` — measured ACTIVE docs vs Qdrant points.
6. `scripts/compute_bm25_stats.py` — tokenizer `avgdl` → `index_stats.metadata` + evidence.
7. `scripts/crc32_collision_analysis.py` — term_id collision rate on vocab.
8. `scripts/chunking_experiment.py` — fixed_window vs structure_aware (DOC-6).
9. `QdrantChunkStore.ensure_collection` — process-local ready flag (avoid per-upsert index PUTs).

## Dataset path

- Part A: HotpotQA **distractor** paragraphs, seeded shuffle (`seed=42`), target **55,000** unique titles.
- Part B: synthetic under `data/synthetic/` with planted contradictions / incompleteness / injection.
- No assignment attachment in repo; public + synthetic path per DATASET.md.

## Storage decision

Pilot deltas → `docs/evidence/storage_estimate_55k.json`. Full ingest completed: ACTIVE **55,081**, Qdrant **56,890** (`docs/evidence/dataset_counts.json`). Wall-clock at ~0.3–0.6 docs/s was the binding constraint; bulk is resumable via `data/checkpoints/bulk_ingest.json`.

## Design notes

- Pilot-then-estimate before claiming 50k fits free tier.
- CRC32 term ids remain stable across restarts (unlike Python `hash()`).
- Cache `ensure_collection` for cloud Qdrant to avoid per-upsert index PUTs.
- `structure_aware` can remain the default production strategy even if `fixed_window` wins DOC-6 on chunk count.
- Bulk resume skips unchanged `external_key`s to avoid re-embedding.

## Limits

- Do not claim ≥50k without `dataset_counts.json` measured ACTIVE ≥50k.
- Qdrant Free disk/RAM API fields often unavailable; use lower-bound estimates + monitor.
- Windows App Control may block `datasets`/pandas DLLs — parquet+pyarrow path preferred
  (see `docs/evidence/windows_parquet_block.txt`).
- Keep **one** bulk process (file lock in `bulk_ingest.py`) to avoid UniqueViolation races.
- `reconcile.py` must not call Qdrant version-cleanup for every ACTIVE doc (O(n)
  remote deletes); only multi-version docs.
