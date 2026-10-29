# Phase 3 notes — hybrid retrieval

## Key functions (interview map)

1. `app.retrieval.tokenizer.tokenize` — NFKC + `\w+` + stopwords + Snowball (`PyStemmer`).
2. `app.retrieval.bm25_sparse.term_id` / `bm25_tf_weight` / `Bm25Encoder` — stable CRC32 ids; document TF weights; query unique terms @ 1.0.
3. `ChunkStore.search_dense` / `search_sparse` — Qdrant `query_points` + in-memory cosine/dot; filters include `active_versions`.
4. `app.retrieval.fusion.rrf_fuse` — `sum 1/(k+rank)`, k=60; ties by `chunk_id`.
5. `app.retrieval.fusion.weighted_fuse` — min-max per list then `α·dense + (1-α)·sparse`.
6. `app.retrieval.reranker` features — fused, coverage, title/heading, entity/number, proximity; then MMR, near-dup collapse, per-doc cap.
7. `HybridRetriever.retrieve` — modes `dense|sparse|hybrid_rrf|hybrid_weighted|hybrid_rerank`; defensive active-version filter.
8. `DocumentLifecycle` optional `sparse_encoder` — fills sparse indices/values on upsert.

## Interview questions

1. Why not Python `hash()` for sparse term ids?
2. Where does IDF live if our BM25 encoder only emits TF weights?
3. How does RRF differ from weighted score fusion, and when does each win?
4. Walk the five reranker features; which would fire on a rare SKU + title match?
5. How do you keep deleted / stale versions out of answers without trusting Qdrant alone?
6. Prove that dense-only can fail and sparse can rescue (and vice versa) — what does the test corpus look like?
7. Why is `InMemoryChunkStore` allowed in Protocol tests but insufficient for VEC-1 adapter proof?

## Limits

- `bm25_avgdl` defaults to 100 until corpus stats are computed at bulk ingest.
- Qdrant Cloud remote path not smoked in Phase 3 evidence (embedded `:memory:` was).
- Reranker weights are defaults; tune on a held-out **dev** set in Phase 6 eval, not by peeking at the final test set.
