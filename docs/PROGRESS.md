# Progress

## Phase 0 — Complete

Render Free + Neon + Qdrant. Northflank rejected (card).

## Phase 1 — Complete (2026-10-29)

- Local quality + 512 MB container bench (peak **284.6 MiB**)
- Public URL: https://ai-investigation-engine-scyz.onrender.com
- Evidence: `docs/evidence/phase1.txt`, `docs/evidence/phase1_deploy.txt`

## Phase 2 — Complete (2026-10-29)

Parsing, chunking, duplicates, document lifecycle (DOC-1 to DOC-5).

- Parsers: TXT, MD, PDF, DOCX, HTML, JSONL, CSV
- Chunkers: `fixed_window` + `structure_aware`
- Dedup: exact SHA-256 + SimHash bands
- Lifecycle add/update/delete + reconcile
- Verification: **ruff / mypy clean; 52 pytest passed** (`docs/evidence/phase2.txt`)
- Note: local tests use `InMemoryChunkStore` when embedded Qdrant gRPC is blocked by WDAC; `QdrantChunkStore` remains the production adapter. Embeddings still placeholders (Phase 3).

## Phase 3 — Next

Embeddings, BM25 sparse encoder, hybrid retrieval, custom reranker (VEC-1 to VEC-4).
