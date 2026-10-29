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

## Phase 4 — Partial (2026-10-29) — NOT complete

LLM gateway + hand-written investigation engine implemented; scripted unit/integration tests green.

- Gateway: Groq primary → Gemini OpenAI-compatible fallback; retries/budget/JSON repair/`ScriptedLLM`
- Engine stages: guard → plan → tools → claims → aggregate → contradictions → sufficiency → synthesize → verify
- Verification: **ruff / mypy clean; 98 pytest passed, 1 skipped** (`docs/evidence/phase4.txt`)
- Live LLM: **NOT run** (GROQ_API_KEY / GEMINI_API_KEY absent) — no `phase4_live_trace.json`
- **HUMAN ACTION REQUIRED:** set free-tier keys locally, run `make test-live`, then mark Complete only after live evidence exists
- Limits still open: Qdrant Cloud unverified; bm25_avgdl default; CRC32 collisions pending; retrieval eval pending
- Phase 5 (API/UI) not started

## Phase 5 — Next

Ask API + static UI (do not start until Phase 4 live evidence accepted).
