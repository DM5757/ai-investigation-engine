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
- Qdrant coverage clarified in `docs/evidence/phase2_qdrant_coverage.txt` (Protocol vs real adapter).
- Windows tooling notes: `docs/evidence/windows_security_tools.txt`

## Phase 3 — Complete (2026-10-29)

Embeddings, custom BM25 sparse encoder, dense+sparse Qdrant retrieval, RRF/weighted fusion, custom feature reranker (VEC-1 to VEC-4).

- `FastEmbedProvider` used in dense-rescue integration (real nonzero BGE-small vectors)
- Custom BM25 (`zlib.crc32` term ids) + modes: dense / sparse / hybrid_rrf / hybrid_weighted / hybrid_rerank
- `QdrantChunkStore.search_dense` / `search_sparse` verified via dedicated isinstance test
- Verification: **ruff / mypy clean; 74 pytest passed, 0 skipped** (`docs/evidence/phase3.txt`)
- Limitation: Qdrant Cloud remote URL not exercised this session (embedded `:memory:` ok)

## Phase 4 — Next

LLM gateway + investigation / RAG (do not start until Phase 3 docs accepted).
