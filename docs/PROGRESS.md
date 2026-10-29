# Progress

## Phase 0 — Complete

Render Free + Neon + Qdrant. Northflank rejected (card).

## Phase 1 — Complete (2026-10-29)

- Local quality + 512 MB container bench (peak **284.6 MiB**)
- Public URL: https://ai-investigation-engine-scyz.onrender.com
- Evidence: `docs/evidence/phase1.txt`, `docs/evidence/phase1_deploy.txt`

## Phase 2 — Complete (2026-10-29)

Parsing, chunking, duplicates, document lifecycle (DOC-1 to DOC-5).
Evidence: `docs/evidence/phase2.txt`, `phase2_qdrant_coverage.txt`

## Phase 3 — Complete (2026-10-29)

Hybrid retrieval (VEC-1 to VEC-4). Evidence: `docs/evidence/phase3.txt`

## Phase 4 — Complete (2026-10-29)

LLM gateway + investigation engine (RAG-1 to RAG-8).

- Scripted unit/integration: gateway, quotes, contradictions, sufficiency, injection, verifier
- **Live Groq smoke passed** (`tests/live`, 11.71s): multi-doc question → `answered` with verified citations from `live_a` + `live_b`
- Evidence: `docs/evidence/phase4.txt`, `docs/evidence/phase4_live_trace.json`, `docs/evidence/llm_models_verified.txt`
- Default pytest excludes `live` marker to protect free-tier quotas; use `make test-live`
- Limits still open: Qdrant Cloud remote; bm25_avgdl; CRC32 collisions; retrieval eval

## Phase 5 — Complete (2026-10-29)

Ask API + vanilla JS UI (documents, query, sources, stats, eval stub, health).

- Admin-token mutating document routes; public rate-limited `/api/query`
- Static UI tabs: Ask | Documents | Corpus stats | Evaluation | Health
- Tests: `test_api_documents`, `test_api_query`, `test_api_ui_static` (+ ratelimit/security unit)
- Evidence: `docs/evidence/phase5.txt`, `docs/evidence/phase5_ui_checklist.txt`
- Local verification: ruff/mypy clean; **119 passed**, 1 deselected (`live`)
- Render: Phase 1 public URL unchanged; Phase 5 endpoints not claimed verified on Render
- Gaps still open: Qdrant Cloud; bm25_avgdl; CRC32 collisions; retrieval eval

## Hotfix — Neon / Psycopg 3 (2026-10-29)

- Root cause: `postgresql://` → SQLAlchemy loaded missing `psycopg2`
- Fix: normalize to `postgresql+psycopg://`; ready → sanitized 503 on DB failure
- Neon: migrate to alembic `0002`; evidence `docs/evidence/psycopg3_neon_fix.txt`
- Suite after fix: **129 passed**, 1 deselected

## Phase 6 — In progress (2026-10-29) — bulk overnight

Corpus scale + DOC-6 chunking experiment (after prod checkpoint).

- Hotpot distractor corpus **55,000** unique `hotpotqa:<title>` built (`data/manifests/corpus_manifest.json`, sha256 `528db785…`, validation split)
- Synthetic multi-format + `synthetic_truth.json` (all 8 files ingested incl. joined JSONL)
- Pilot ingest measured; **55k storage GO** (`storage_estimate_55k.json`)
- Bulk ingest **running under** `scripts/watch_bulk_ingest.ps1` (file-locked, checkpointed). **Do not claim ≥50k** until `dataset_counts.json` ACTIVE≥50000
- BM25 avgdl **55.64** (pilot-scale); CRC32 collisions **0** on ~20k terms — recompute after full bulk
- DOC-6: `fixed_window` wins on chunk count with tied Recall@K; default strategy still `structure_aware`
- Windows: App Control blocks `datasets`/pandas; pyarrow parquet streaming OK (`windows_parquet_block.txt`)
- Evidence: `docs/evidence/phase6.txt`, `pilot_ingest.json`, `storage_estimate_55k.json`, `bm25_corpus_stats.json`, `crc32_collisions.json`, `eval/results/chunking_comparison.*`
- Phase 7 **started**: eval harness + 75-question set + preliminary dense vs hybrid and baseline vs investigation runs (corpus still &lt;50k — results labeled preliminary)
- Batched bulk ingest (`--batch-size 64`) ~1.5–2.5 docs/s after repair of interrupted INDEXING rows; watchdog resumes from `data/checkpoints/bulk_ingest.json`
