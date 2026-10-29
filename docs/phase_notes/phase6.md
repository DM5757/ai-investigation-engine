# Phase 6 notes — Corpus scale + DOC-6 chunking

## Key modules (interview map)

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

Pilot deltas → `docs/evidence/storage_estimate_55k.json`. Full ingest **go** on Neon/Qdrant free headroom (marginal bytes). Wall-clock at ~0.3–0.6 docs/s is the binding constraint; bulk is resumable via `data/checkpoints/bulk_ingest.json`.

## Interview questions

1. Why pilot-then-estimate before claiming 50k fits free tier?
2. Why CRC32 term ids instead of Python `hash()`?
3. Why cache `ensure_collection` for cloud Qdrant?
4. When would you keep `structure_aware` as default even if `fixed_window` wins DOC-6 on chunk count?
5. How does bulk resume without re-embedding unchanged `external_key`s?

## Limits

- Do not claim ≥50k without `dataset_counts.json` measured ACTIVE ≥50k.
- Qdrant Free disk/RAM API fields often unavailable; use lower-bound estimates + monitor.
- Windows App Control may block `datasets`/pandas DLLs — parquet+pyarrow path preferred
  (see `docs/evidence/windows_parquet_block.txt`). The blocked `.pyd` is
  `pyarrow/_dataset_parquet.cp313-win_amd64.pyd`; basic `pyarrow.parquet` streaming works.
- Bulk wall-clock (~0.5–0.7 creates/s) is the binding free-tier constraint; use
  `scripts/watch_bulk_ingest.ps1` for overnight resume. Keep **one** bulk process
  (file lock in `bulk_ingest.py`) to avoid UniqueViolation races.
- `reconcile.py` must not call Qdrant version-cleanup for every ACTIVE doc (O(n)
  remote deletes); only multi-version docs.
- Phase 7 (eval harness) not started.
