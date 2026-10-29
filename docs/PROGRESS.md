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

## Phase 5 — Next

Ask API + static UI (documents, query, sources). Do not start until Phase 4 review accepted.
