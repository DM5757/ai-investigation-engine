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

## Phase 6 — Complete (2026-10-29 evening) — DATA-1 ≥50k verified

Corpus scale + DOC-6 chunking experiment.

- Hotpot distractor corpus **55,000** unique `hotpotqa:<title>` built; synthetic multi-format ingested
- Bulk ingest finished under `scripts/watch_bulk_ingest.ps1` (batch size **16**, Qdrant upsert retries)
- Checkpoint: `done=true`, `processed=55000` (`data/checkpoints/bulk_ingest.json`)
- **Measured 2026-10-30 (re-verified):** ACTIVE **55,081**, FAILED **0**, DELETED **5**, Qdrant points **56,890**, `meets_data1_50k: true`
- **Chunk↔vector accounting:** Postgres `chunks` total **56,900** = ACTIVE chunk rows **56,890** + DELETED-document chunk rows **10**. Qdrant points equal ACTIVE chunk rows exactly; the historical “10-point gap” is retained metadata for deleted docs, not missing index coverage.
- Evidence: `docs/evidence/dataset_counts.json`, `docs/evidence/bulk_ingest.json`

## Phase 7 — Evaluation (2026-10-29) — partial LLM answer coverage

- Active-gold eval set (57 q); retrieval `active_retrieval_v1` **n_scored=54** (dense Recall@10 0.963 vs hybrid MRR 0.948) on ~3.4k ACTIVE — re-run on full corpus is a post-submission follow-up
- Investigation budget-reset in eval harness; `active_investigation_v2` test split **27/37** `llm_unavailable` after Groq **200k TPD** exhaustion
- Deterministic contradiction/abstention gates **PASS**; live status labeling historically weak
- Early submission tag `submission-2026-10-29` @ `1ab164d` **preserved unchanged**

## Post-submission quality (2026-10-30) — in progress

- Publish verified 55k milestone evidence
- Fix per-query LLM budget, question-conditioned sufficiency, retrieval/citation precision, synthesis status labeling, `/api/version` git SHA
- Re-run full-corpus retrieval eval and controlled answer eval; verify Roanoke probes on Render

## Human actions still required

1. Own interview defense of AI-assisted work (`docs/AI_USAGE_REPORT.md`).
2. Confirm Render dashboard deploy SHA after each push.
3. Optional: provide a Groq/Gemini quota window for full investigation answer eval.
