"""Qdrant chunk index store (Protocol + embedded/local client + in-memory fallback)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


def collection_name(strategy: str, embedding_short: str = "bge-small") -> str:
    """Canonical collection naming: chunks__{strategy}__{embedding}."""
    safe_strategy = strategy.replace("-", "_")
    safe_embed = embedding_short.replace("-", "_")
    return f"chunks__{safe_strategy}__{safe_embed}"


@dataclass
class ChunkPoint:
    """One chunk vector point ready for upsert."""

    point_id: str
    doc_id: str
    version: int
    chunk_index: int
    content_hash: str
    text: str
    dense_vector: list[float]
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)
    payload_extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "doc_id": self.doc_id,
            "version": self.version,
            "chunk_index": self.chunk_index,
            "content_hash": self.content_hash,
            "text": self.text,
        }
        payload.update(self.payload_extra)
        return payload


@runtime_checkable
class ChunkStore(Protocol):
    """Index operations used by document lifecycle and reconcile."""

    collection: str

    def ensure_collection(self) -> None:
        """Create the collection if it does not exist."""

    def upsert_chunks(self, points: list[ChunkPoint]) -> None:
        """Upsert chunk points (dense required; sparse optional)."""

    def delete_by_doc_id(self, doc_id: str) -> None:
        """Delete all points for a document."""

    def delete_by_doc_version_ne(self, doc_id: str, version: int) -> None:
        """Delete points for doc_id where version != version."""

    def list_point_ids_for_doc(self, doc_id: str) -> list[str]:
        """Return point ids for a document."""

    def get_payloads(self, point_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return payload map keyed by point id."""

    def count_for_doc(self, doc_id: str, *, version: int | None = None) -> int:
        """Count points for a document, optionally filtered by version."""


class InMemoryChunkStore:
    """Pure-Python ChunkStore for unit/integration tests without native gRPC."""

    def __init__(
        self,
        *,
        strategy: str = "structure_aware",
        embedding_short: str = "bge-small",
        dense_size: int = 384,
    ) -> None:
        self.strategy = strategy
        self.embedding_short = embedding_short
        self.dense_size = dense_size
        self.collection = collection_name(strategy, embedding_short)
        self._points: dict[str, tuple[list[float], dict[str, Any]]] = {}
        self._ready = False

    def ensure_collection(self) -> None:
        self._ready = True

    def upsert_chunks(self, points: list[ChunkPoint]) -> None:
        self.ensure_collection()
        for point in points:
            dense = list(point.dense_vector) or [0.0] * self.dense_size
            if len(dense) != self.dense_size:
                raise ValueError(f"dense vector length {len(dense)} != {self.dense_size}")
            self._points[point.point_id] = (dense, point.to_payload())

    def delete_by_doc_id(self, doc_id: str) -> None:
        self.ensure_collection()
        drop = [
            pid
            for pid, (_, payload) in self._points.items()
            if payload.get("doc_id") == doc_id
        ]
        for pid in drop:
            del self._points[pid]

    def delete_by_doc_version_ne(self, doc_id: str, version: int) -> None:
        self.ensure_collection()
        drop = [
            pid
            for pid, (_, payload) in self._points.items()
            if payload.get("doc_id") == doc_id and payload.get("version") != version
        ]
        for pid in drop:
            del self._points[pid]

    def list_point_ids_for_doc(self, doc_id: str) -> list[str]:
        self.ensure_collection()
        return [
            pid
            for pid, (_, payload) in self._points.items()
            if payload.get("doc_id") == doc_id
        ]

    def get_payloads(self, point_ids: list[str]) -> dict[str, dict[str, Any]]:
        self.ensure_collection()
        out: dict[str, dict[str, Any]] = {}
        for pid in point_ids:
            item = self._points.get(pid)
            if item is not None:
                out[pid] = dict(item[1])
        return out

    def count_for_doc(self, doc_id: str, *, version: int | None = None) -> int:
        self.ensure_collection()
        count = 0
        for _, payload in self._points.values():
            if payload.get("doc_id") != doc_id:
                continue
            if version is not None and payload.get("version") != version:
                continue
            count += 1
        return count


class QdrantChunkStore:
    """Chunk store backed by qdrant-client (memory, path, or remote URL)."""

    def __init__(
        self,
        client: Any,
        *,
        strategy: str = "structure_aware",
        embedding_short: str = "bge-small",
        dense_size: int = 384,
        enable_sparse: bool = True,
    ) -> None:
        self.client = client
        self.strategy = strategy
        self.embedding_short = embedding_short
        self.dense_size = dense_size
        self.enable_sparse = enable_sparse
        self.collection = collection_name(strategy, embedding_short)

    @classmethod
    def local(
        cls,
        *,
        path: str | None = None,
        strategy: str = "structure_aware",
        embedding_short: str = "bge-small",
        dense_size: int = 384,
        enable_sparse: bool = True,
    ) -> QdrantChunkStore:
        """Build a store using embedded Qdrant (`:memory:` or filesystem path)."""
        from qdrant_client import QdrantClient

        client = QdrantClient(path=path) if path else QdrantClient(location=":memory:")
        return cls(
            client,
            strategy=strategy,
            embedding_short=embedding_short,
            dense_size=dense_size,
            enable_sparse=enable_sparse,
        )

    @classmethod
    def remote(
        cls,
        url: str,
        *,
        api_key: str | None = None,
        strategy: str = "structure_aware",
        embedding_short: str = "bge-small",
        dense_size: int = 384,
        enable_sparse: bool = True,
    ) -> QdrantChunkStore:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url, api_key=api_key)
        return cls(
            client,
            strategy=strategy,
            embedding_short=embedding_short,
            dense_size=dense_size,
            enable_sparse=enable_sparse,
        )

    def ensure_collection(self) -> None:
        from qdrant_client.http import models as qmodels

        names = {c.name for c in self.client.get_collections().collections}
        if self.collection in names:
            return
        vectors_config: dict[str, Any] = {
            DENSE_VECTOR_NAME: qmodels.VectorParams(
                size=self.dense_size,
                distance=qmodels.Distance.COSINE,
            )
        }
        sparse_config: dict[str, Any] | None = None
        if self.enable_sparse:
            sparse_config = {
                SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
                    index=qmodels.SparseIndexParams(on_disk=False),
                )
            }
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=vectors_config,
            sparse_vectors_config=sparse_config,
        )

    def upsert_chunks(self, points: list[ChunkPoint]) -> None:
        if not points:
            return
        from qdrant_client.http import models as qmodels

        self.ensure_collection()
        qpoints: list[Any] = []
        for point in points:
            dense = list(point.dense_vector)
            if len(dense) != self.dense_size:
                if not dense:
                    dense = [0.0] * self.dense_size
                else:
                    raise ValueError(
                        f"dense vector length {len(dense)} != {self.dense_size}"
                    )
            vector: dict[str, Any] = {DENSE_VECTOR_NAME: dense}
            if self.enable_sparse and point.sparse_indices:
                vector[SPARSE_VECTOR_NAME] = qmodels.SparseVector(
                    indices=point.sparse_indices,
                    values=point.sparse_values,
                )
            qpoints.append(
                qmodels.PointStruct(
                    id=point.point_id,
                    vector=vector,
                    payload=point.to_payload(),
                )
            )
        self.client.upsert(collection_name=self.collection, points=qpoints)

    def delete_by_doc_id(self, doc_id: str) -> None:
        from qdrant_client.http import models as qmodels

        self.ensure_collection()
        self.client.delete(
            collection_name=self.collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="doc_id",
                            match=qmodels.MatchValue(value=doc_id),
                        )
                    ]
                )
            ),
        )

    def delete_by_doc_version_ne(self, doc_id: str, version: int) -> None:
        from qdrant_client.http import models as qmodels

        self.ensure_collection()
        self.client.delete(
            collection_name=self.collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="doc_id",
                            match=qmodels.MatchValue(value=doc_id),
                        )
                    ],
                    must_not=[
                        qmodels.FieldCondition(
                            key="version",
                            match=qmodels.MatchValue(value=version),
                        )
                    ],
                )
            ),
        )

    def list_point_ids_for_doc(self, doc_id: str) -> list[str]:
        from qdrant_client.http import models as qmodels

        self.ensure_collection()
        points, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id",
                        match=qmodels.MatchValue(value=doc_id),
                    )
                ]
            ),
            limit=10_000,
            with_payload=False,
            with_vectors=False,
        )
        return [str(p.id) for p in points]

    def get_payloads(self, point_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not point_ids:
            return {}
        self.ensure_collection()
        records = self.client.retrieve(
            collection_name=self.collection,
            ids=point_ids,
            with_payload=True,
            with_vectors=False,
        )
        out: dict[str, dict[str, Any]] = {}
        for rec in records:
            payload = dict(rec.payload or {})
            out[str(rec.id)] = payload
        return out

    def count_for_doc(self, doc_id: str, *, version: int | None = None) -> int:
        from qdrant_client.http import models as qmodels

        self.ensure_collection()
        must: list[Any] = [
            qmodels.FieldCondition(
                key="doc_id",
                match=qmodels.MatchValue(value=doc_id),
            )
        ]
        if version is not None:
            must.append(
                qmodels.FieldCondition(
                    key="version",
                    match=qmodels.MatchValue(value=version),
                )
            )
        result = self.client.count(
            collection_name=self.collection,
            count_filter=qmodels.Filter(must=must),
            exact=True,
        )
        return int(result.count)


def make_local_chunk_store(
    *,
    path: str | None = None,
    strategy: str = "structure_aware",
    embedding_short: str = "bge-small",
    dense_size: int = 384,
    enable_sparse: bool = True,
) -> ChunkStore:
    """Prefer embedded Qdrant; fall back to InMemoryChunkStore if gRPC is blocked."""
    try:
        return QdrantChunkStore.local(
            path=path,
            strategy=strategy,
            embedding_short=embedding_short,
            dense_size=dense_size,
            enable_sparse=enable_sparse,
        )
    except Exception:  # noqa: BLE001 — native gRPC/DLL may be blocked by WDAC
        return InMemoryChunkStore(
            strategy=strategy,
            embedding_short=embedding_short,
            dense_size=dense_size,
        )
