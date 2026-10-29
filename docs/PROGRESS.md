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

## Phase 6 — Next

Chunking experiment / corpus scale (DOC-6 / DATA-*). Do not start until Phase 5 review accepted.
