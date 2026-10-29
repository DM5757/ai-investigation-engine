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

## Hotfix — Neon / Psycopg 3 (2026-10-29)

- Root cause: `postgresql://` → SQLAlchemy loaded missing `psycopg2`
- Fix: normalize to `postgresql+psycopg://`; ready → sanitized 503 on DB failure
- Neon: migrate to alembic `0002`; evidence `docs/evidence/psycopg3_neon_fix.txt`

## Phase 6 — In progress (2026-10-29) — bulk overnight

Corpus scale + DOC-6 chunking experiment.

- Hotpot distractor corpus **55,000** unique `hotpotqa:<title>` built
- Synthetic multi-format + `synthetic_truth.json` ingested
- Bulk ingest under `scripts/watch_bulk_ingest.ps1` (file-locked, checkpointed)
- **Qdrant write-timeout mitigation (2026-10-29 afternoon):** upsert chunking + retries/backoff/split; batch size **16**; on restart repaired **321** FAILED write-timeout rows back to ACTIVE
- **Do not claim ≥50k** until `dataset_counts.json` `meets_data1_50k: true`
- Measured later the same day (post-repair): ACTIVE ≈ **5.1k+** and climbing; FAILED cleared after repair; Neon↔Qdrant consistent

## Phase 7 — Evaluation (2026-10-29) — partial LLM answer coverage

- Active-gold eval set (57 q); retrieval `active_retrieval_v1` **n_scored=54** (dense Recall@10 0.963 vs hybrid MRR 0.948)
- Investigation budget-reset fix; `active_investigation_v2` ran test split but **27/37** hit `llm_unavailable` after Groq **200k TPD** exhaustion
- Deterministic contradiction/abstention gates **PASS**; live status labeling still weak (`docs/evidence/behavioral_rag_smoke.json`)
- Gemini tool round-trip fixed by preserving `thought_signature` / `extra_content`
- Prod E2E re-verified (lifecycle + UI); query degraded while Groq TPD exhausted
- Early submission tag `submission-2026-10-29` @ `1ab164d` **preserved unchanged**
- Submission-ready continuation commit: recorded after push in git log (see latest `main`)

## Human actions still required before deadline

1. Complete independent-verification checklist in `docs/AI_USAGE_REPORT.md` (do not leave AI-filled claims).
2. Confirm Render auto-deployed the latest `main` commit (dashboard SHA).
3. Optional: after Groq TPD resets, re-run investigation eval with `--pause-s 3 --stop-after-llm-unavailable 3`.
