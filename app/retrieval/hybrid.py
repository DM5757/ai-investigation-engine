"""Hybrid dense + sparse retriever with fusion modes."""

from __future__ import annotations

from collections.abc import Mapping
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
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.bm25 = bm25
        self.settings = settings or get_settings()

    def retrieve(
        self,
        query: str,
        k: int = 10,
        *,
        mode: RetrievalMode = "hybrid_rrf",
        filters: Mapping[str, Any] | None = None,
        active_versions: Mapping[str, int] | None = None,
    ) -> list[RetrievalHit]:
        """Retrieve top-k chunks for ``query`` under the selected mode."""
        if k <= 0:
            return []
        store_filters = dict(filters) if filters else None
        if active_versions and store_filters is not None:
            store_filters = {**store_filters, "active_versions": dict(active_versions)}
        elif active_versions:
            store_filters = {"active_versions": dict(active_versions)}

        n_dense = self.settings.n_dense
        n_sparse = self.settings.n_sparse

        dense_chunks: list[ScoredChunk] = []
        sparse_chunks: list[ScoredChunk] = []
        dense_ranks: dict[str, int] = {}
        sparse_ranks: dict[str, int] = {}

        if mode in ("dense", "hybrid_rrf", "hybrid_weighted", "hybrid_rerank"):
            dense_vec = self.embedder.embed_query(query)
            dense_hits = self.store.search_dense(
                dense_vec, n_dense, filters=store_filters
            )
            dense_chunks = [_hit_to_scored(h) for h in dense_hits]
            dense_chunks = _filter_active_versions(dense_chunks, active_versions)
            dense_ranks = {c.chunk_id: i + 1 for i, c in enumerate(dense_chunks)}

        if mode in ("sparse", "hybrid_rrf", "hybrid_weighted", "hybrid_rerank"):
            sparse = self.bm25.encode_query(query)
            sparse_hits = self.store.search_sparse(
                sparse.indices, sparse.values, n_sparse, filters=store_filters
            )
            sparse_chunks = [_hit_to_scored(h) for h in sparse_hits]
            sparse_chunks = _filter_active_versions(sparse_chunks, active_versions)
            sparse_ranks = {c.chunk_id: i + 1 for i, c in enumerate(sparse_chunks)}

        if mode == "dense":
            return _to_hits(dense_chunks[:k], mode=mode, dense_ranks=dense_ranks)
        if mode == "sparse":
            return _to_hits(sparse_chunks[:k], mode=mode, sparse_ranks=sparse_ranks)

        if mode == "hybrid_rrf":
            fused = rrf_fuse(
                [dense_chunks, sparse_chunks], k=self.settings.rrf_k
            )
            return _to_hits(
                fused[:k],
                mode=mode,
                dense_ranks=dense_ranks,
                sparse_ranks=sparse_ranks,
            )

        fused_weighted = weighted_fuse(
            dense_chunks,
            sparse_chunks,
            alpha=self.settings.fusion_alpha,
        )
        if mode == "hybrid_weighted":
            return _to_hits(
                fused_weighted[:k],
                mode=mode,
                dense_ranks=dense_ranks,
                sparse_ranks=sparse_ranks,
            )

        # hybrid_rerank
        weights = RerankerWeights(
            fused=self.settings.rerank_w_fused,
            coverage=self.settings.rerank_w_coverage,
            title_heading=self.settings.rerank_w_title,
            entity_number=self.settings.rerank_w_entity,
            proximity=self.settings.rerank_w_proximity,
            mmr_lambda=self.settings.rerank_mmr_lambda,
        )
        hits = rerank(
            query,
            fused_weighted,
            weights=weights,
            per_doc_cap=self.settings.per_doc_cap,
            limit=k,
        )
        for hit in hits:
            hit.dense_rank = dense_ranks.get(hit.chunk.chunk_id)
            hit.sparse_rank = sparse_ranks.get(hit.chunk.chunk_id)
            hit.mode = mode
        return hits
