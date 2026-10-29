# Phase 2 notes — parsing, chunking, dedup, lifecycle

## What was built

- Format parsers (TXT/MD/PDF/DOCX/HTML/JSONL/CSV) under `app/ingestion/parsers/`
- Text normalizer + metadata helpers
- Chunkers: `fixed_window`, `structure_aware` (+ sentence splitter)
- SHA-256 content hashing and custom SimHash (5-word shingles, 4×16-bit bands)
- SQLAlchemy models: documents, document_versions, chunks, simhash_bands, index_stats
- Alembic `0002_documents_lifecycle`
- `DocumentLifecycle` add/update/delete with PENDING→INDEXING→ACTIVE (and delete path)
- `reconcile_session` / `scripts/reconcile.py` for crash windows
- `ChunkStore` Protocol: `QdrantChunkStore` + `InMemoryChunkStore`

## Key functions / modules

1. `app.ingestion.parsers.registry.parse_document` — extension → parser
2. `app.ingestion.normalize.normalize_text`
3. `app.ingestion.chunking.registry.get_chunker`
4. `app.ingestion.dedup.simhash.compute_simhash` / `find_near_duplicates`
5. `app.ingestion.pipeline.prepare_document`
6. `app.ingestion.lifecycle.DocumentLifecycle.add|update|delete`
7. `app.ingestion.reconcile.reconcile_session`
8. `app.index.qdrant_store.make_local_chunk_store`

## Interview questions to practice

1. Walk PENDING → INDEXING → ACTIVE and what is transactional vs external (Qdrant).
2. Exact duplicate vs near-duplicate: when do we refuse to index vs flag?
3. How do chunk offsets prove the chunker did not invent text?
4. Why is SimHash banded, and what does Hamming distance mean here?
5. If the process dies after Qdrant upsert but before ACTIVE, what does reconcile do?
6. Why can tests pass without a live Qdrant process on Windows?
