"""Hybrid dense + sparse retriever with fusion modes."""

from __future__ import annotations

import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from app.config import Settings, get_settings
from app.embeddings.provider import EmbeddingProvider
from app.index.qdrant_store import ChunkStore, SearchHit
from app.retrieval.bm25_sparse import Bm25Encoder
from app.retrieval.fusion import rrf_fuse, weighted_fuse
from app.retrieval.reranker import RerankerWeights, rerank
from app.retrieval.types import RetrievalHit, ScoredChunk

RetrievalMode = Literal[
    "dense",
    "sparse",
    "hybrid_rrf",
    "hybrid_weighted",
    "hybrid_rerank",
]


def _hit_to_scored(hit: SearchHit) -> ScoredChunk:
    payload = hit.payload
    heading = payload.get("heading_path")
    if isinstance(heading, list):
        heading = " > ".join(str(h) for h in heading)
    return ScoredChunk(
        chunk_id=hit.point_id,
        doc_id=str(payload.get("doc_id", "")),
        version=int(payload.get("version", 0)),
        text=str(payload.get("text", "")),
        score=float(hit.score),
        chunk_index=int(payload.get("chunk_index", 0)),
        title=payload.get("title") if isinstance(payload.get("title"), str) else None,
        heading_path=str(heading) if heading else None,
        near_duplicate_of=(
            str(payload["near_duplicate_of"])
            if payload.get("near_duplicate_of") is not None
            else None
        ),
        content_hash=(
            str(payload["content_hash"]) if payload.get("content_hash") is not None else None
        ),
        payload=dict(payload),
    )


def _filter_active_versions(
    chunks: list[ScoredChunk],
    active_versions: Mapping[str, int] | None,
) -> list[ScoredChunk]:
    if not active_versions:
        return chunks
    out: list[ScoredChunk] = []
    for chunk in chunks:
        expected = active_versions.get(chunk.doc_id)
        if expected is None:
            continue
        if chunk.version != expected:
            continue
        out.append(chunk)
    return out


def _to_hits(
    chunks: list[ScoredChunk],
    *,
    mode: str,
    dense_ranks: dict[str, int] | None = None,
    sparse_ranks: dict[str, int] | None = None,
) -> list[RetrievalHit]:
    hits: list[RetrievalHit] = []
    for chunk in chunks:
        hits.append(
            RetrievalHit(
                chunk=chunk,
                dense_rank=(dense_ranks or {}).get(chunk.chunk_id),
                sparse_rank=(sparse_ranks or {}).get(chunk.chunk_id),
                fused_score=chunk.score,
                mode=mode,
            )
        )
    return hits


class HybridRetriever:
    """Dense + BM25 sparse retrieval with RRF / weighted / rerank modes."""

    def __init__(
        self,
        store: ChunkStore,
        embedder: EmbeddingProvider,
        bm25: Bm25Encoder,
        settings: Settings | None = None,
        *,
        default_mode: RetrievalMode = "hybrid_rrf",
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.bm25 = bm25
        self.settings = settings or get_settings()
        self.default_mode: RetrievalMode = default_mode
        # Filled by the most recent retrieve() call (milliseconds, monotonic).
        self.last_timings: dict[str, float] = {}

    def retrieve(
        self,
        query: str,
        k: int = 10,
        *,
        mode: RetrievalMode | None = None,
        filters: Mapping[str, Any] | None = None,
        active_versions: Mapping[str, int] | None = None,
    ) -> list[RetrievalHit]:
        """Retrieve top-k chunks for ``query`` under the selected mode."""
        if k <= 0:
            self.last_timings = {}
            return []
        mode = mode or self.default_mode
        store_filters = dict(filters) if filters else None
        if active_versions and store_filters is not None:
            store_filters = {**store_filters, "active_versions": dict(active_versions)}
        elif active_versions:
            store_filters = {"active_versions": dict(active_versions)}

        n_dense = self.settings.n_dense
        n_sparse = self.settings.n_sparse
        t_all = time.perf_counter()
        timings: dict[str, float] = {}

        need_dense = mode in ("dense", "hybrid_rrf", "hybrid_weighted", "hybrid_rerank")
        need_sparse = mode in ("sparse", "hybrid_rrf", "hybrid_weighted", "hybrid_rerank")

        dense_chunks: list[ScoredChunk] = []
        sparse_chunks: list[ScoredChunk] = []
        dense_ranks: dict[str, int] = {}
        sparse_ranks: dict[str, int] = {}

        def _dense_branch() -> tuple[list[ScoredChunk], dict[str, int], dict[str, float]]:
            local: dict[str, float] = {}
            t0 = time.perf_counter()
            dense_vec = self.embedder.embed_query(query)
            local["embed_ms"] = (time.perf_counter() - t0) * 1000.0
            t1 = time.perf_counter()
            dense_hits = self.store.search_dense(
                dense_vec, n_dense, filters=store_filters
            )
            local["qdrant_dense_ms"] = (time.perf_counter() - t1) * 1000.0
            chunks = [_hit_to_scored(h) for h in dense_hits]
            chunks = _filter_active_versions(chunks, active_versions)
            ranks = {c.chunk_id: i + 1 for i, c in enumerate(chunks)}
            return chunks, ranks, local

        def _sparse_branch() -> tuple[list[ScoredChunk], dict[str, int], dict[str, float]]:
            local: dict[str, float] = {}
            t0 = time.perf_counter()
            sparse = self.bm25.encode_query(query)
            local["bm25_encode_ms"] = (time.perf_counter() - t0) * 1000.0
            t1 = time.perf_counter()
            sparse_hits = self.store.search_sparse(
                sparse.indices, sparse.values, n_sparse, filters=store_filters
            )
            local["qdrant_sparse_ms"] = (time.perf_counter() - t1) * 1000.0
            chunks = [_hit_to_scored(h) for h in sparse_hits]
            chunks = _filter_active_versions(chunks, active_versions)
            ranks = {c.chunk_id: i + 1 for i, c in enumerate(chunks)}
            return chunks, ranks, local

        if need_dense and need_sparse:
            # Overlap embed+dense Qdrant with BM25+sparse Qdrant on free-tier network path.
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_d = pool.submit(_dense_branch)
                fut_s = pool.submit(_sparse_branch)
                dense_chunks, dense_ranks, t_d = fut_d.result()
                sparse_chunks, sparse_ranks, t_s = fut_s.result()
            timings.update(t_d)
            timings.update(t_s)
        elif need_dense:
            dense_chunks, dense_ranks, t_d = _dense_branch()
            timings.update(t_d)
        elif need_sparse:
            sparse_chunks, sparse_ranks, t_s = _sparse_branch()
            timings.update(t_s)

        if mode == "dense":
            hits = _to_hits(dense_chunks[:k], mode=mode, dense_ranks=dense_ranks)
            timings["retrieve_total_ms"] = (time.perf_counter() - t_all) * 1000.0
            self.last_timings = {k_: round(v, 3) for k_, v in timings.items()}
            return hits
        if mode == "sparse":
            hits = _to_hits(sparse_chunks[:k], mode=mode, sparse_ranks=sparse_ranks)
            timings["retrieve_total_ms"] = (time.perf_counter() - t_all) * 1000.0
            self.last_timings = {k_: round(v, 3) for k_, v in timings.items()}
            return hits

        if mode == "hybrid_rrf":
            t_f = time.perf_counter()
            fused = rrf_fuse(
                [dense_chunks, sparse_chunks], k=self.settings.rrf_k
            )
            timings["fusion_ms"] = (time.perf_counter() - t_f) * 1000.0
            hits = _to_hits(
                fused[:k],
                mode=mode,
                dense_ranks=dense_ranks,
                sparse_ranks=sparse_ranks,
            )
            timings["retrieve_total_ms"] = (time.perf_counter() - t_all) * 1000.0
            self.last_timings = {k_: round(v, 3) for k_, v in timings.items()}
            return hits

        t_f = time.perf_counter()
        fused_weighted = weighted_fuse(
            dense_chunks,
            sparse_chunks,
            alpha=self.settings.fusion_alpha,
        )
        timings["fusion_ms"] = (time.perf_counter() - t_f) * 1000.0
        if mode == "hybrid_weighted":
            hits = _to_hits(
                fused_weighted[:k],
                mode=mode,
                dense_ranks=dense_ranks,
                sparse_ranks=sparse_ranks,
            )
            timings["retrieve_total_ms"] = (time.perf_counter() - t_all) * 1000.0
            self.last_timings = {k_: round(v, 3) for k_, v in timings.items()}
            return hits

        # hybrid_rerank
        weights = RerankerWeights(
            fused=self.settings.rerank_w_fused,
            coverage=self.settings.rerank_w_coverage,
            title_heading=self.settings.rerank_w_title,
            entity_number=self.settings.rerank_w_entity,
            proximity=self.settings.rerank_w_proximity,
            mmr_lambda=self.settings.rerank_mmr_lambda,
        )
        t_r = time.perf_counter()
        hits = rerank(
            query,
            fused_weighted,
            weights=weights,
            per_doc_cap=self.settings.per_doc_cap,
            limit=k,
        )
        timings["rerank_ms"] = (time.perf_counter() - t_r) * 1000.0
        for hit in hits:
            hit.dense_rank = dense_ranks.get(hit.chunk.chunk_id)
            hit.sparse_rank = sparse_ranks.get(hit.chunk.chunk_id)
            hit.mode = mode
        timings["retrieve_total_ms"] = (time.perf_counter() - t_all) * 1000.0
        self.last_timings = {k_: round(v, 3) for k_, v in timings.items()}
        return hits
