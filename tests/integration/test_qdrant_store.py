"""Prove real QdrantChunkStore upsert/search (skip if embedded client blocked)."""

from __future__ import annotations

import uuid

import pytest

from app.index.qdrant_store import ChunkPoint, QdrantChunkStore
from app.retrieval.bm25_sparse import Bm25Encoder


def _build_store() -> QdrantChunkStore:
    try:
        store = QdrantChunkStore.local(
            strategy="structure_aware",
            embedding_short="bge-small",
            dense_size=8,
            enable_sparse=True,
        )
    except Exception as exc:  # noqa: BLE001 — WDAC/gRPC may block native client
        pytest.skip(f"QdrantChunkStore.local failed: {exc}")
    if not isinstance(store, QdrantChunkStore):
        pytest.skip("store is not QdrantChunkStore")
    return store


def test_qdrant_chunk_store_upsert_dense_and_sparse_search() -> None:
    store = _build_store()
    assert isinstance(store, QdrantChunkStore)

    bm25 = Bm25Encoder(avgdl=10.0)
    text_a = "alpha widget calibration procedure"
    text_b = "zymopolymer failure mode laboratory"
    sparse_a = bm25.encode_document(text_a)
    sparse_b = bm25.encode_document(text_b)

    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    store.upsert_chunks(
        [
            ChunkPoint(
                point_id=id_a,
                doc_id="doc-a",
                version=1,
                chunk_index=0,
                content_hash="ha",
                text=text_a,
                dense_vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                sparse_indices=sparse_a.indices,
                sparse_values=sparse_a.values,
            ),
            ChunkPoint(
                point_id=id_b,
                doc_id="doc-b",
                version=1,
                chunk_index=0,
                content_hash="hb",
                text=text_b,
                dense_vector=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                sparse_indices=sparse_b.indices,
                sparse_values=sparse_b.values,
            ),
        ]
    )

    dense_hits = store.search_dense(
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        limit=2,
    )
    assert dense_hits
    assert dense_hits[0].point_id == id_a
    assert dense_hits[0].payload["doc_id"] == "doc-a"

    q_sparse = bm25.encode_query("zymopolymer failure")
    sparse_hits = store.search_sparse(q_sparse.indices, q_sparse.values, limit=2)
    assert sparse_hits
    assert sparse_hits[0].point_id == id_b

    filtered = store.search_dense(
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        limit=5,
        filters={"active_versions": {"doc-a": 1}},
    )
    assert all(h.payload.get("doc_id") == "doc-a" for h in filtered)
    assert store.count_for_doc("doc-a", version=1) == 1
