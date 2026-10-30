# Phase 3 notes — hybrid retrieval

## Key modules

1. `app.retrieval.tokenizer.tokenize` — NFKC + `\w+` + stopwords + Snowball (`PyStemmer`).
2. `app.retrieval.bm25_sparse.term_id` / `bm25_tf_weight` / `Bm25Encoder` — stable CRC32 ids; document TF weights; query unique terms @ 1.0.
3. `ChunkStore.search_dense` / `search_sparse` — Qdrant `query_points` + in-memory cosine/dot; filters include `active_versions`.
4. `app.retrieval.fusion.rrf_fuse` — `sum 1/(k+rank)`, k=60; ties by `chunk_id`.
5. `app.retrieval.fusion.weighted_fuse` — min-max per list then `α·dense + (1-α)·sparse`.
6. `app.retrieval.reranker` features — fused, coverage, title/heading, entity/number, proximity; then MMR, near-dup collapse, per-doc cap.
7. `HybridRetriever.retrieve` — modes `dense|sparse|hybrid_rrf|hybrid_weighted|hybrid_rerank`; defensive active-version filter.
8. `DocumentLifecycle` optional `sparse_encoder` — fills sparse indices/values on upsert.

## Design notes

- Prefer CRC32 term ids over Python `hash()` for cross-process stability.
- Sparse encoder emits TF weights; Qdrant IDF modifier supplies collection-level IDF.
- RRF favors rank agreement; weighted fusion needs calibrated score scales.
- Deleted / stale versions are excluded via `active_versions` at store and again defensively in the retriever.
- Dense-only vs sparse-rescue fixtures prove complementary failure modes without claiming BGE failure in production.

## Limits

- `bm25_avgdl` defaults to 100 until corpus stats are computed at bulk ingest.
- Phase 3 evidence used embedded `:memory:` extensively; Qdrant Cloud path verified later via pilot/bulk + live `/api/stats`.
- Reranker weights are defaults; tune on a held-out **dev** set, not by peeking at the final test set.
