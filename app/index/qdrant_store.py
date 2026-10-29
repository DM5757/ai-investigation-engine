"""Qdrant chunk index store (Protocol + embedded/local client + in-memory fallback)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


def collection_name(strategy: str, embedding_short: str = "bge-small") -> str:
    """Canonical collection naming: chunks__{strategy}__{embedding}."""
    safe_strategy = strategy.replace("-", "_")
    safe_embed = embedding_short.replace("-", "_")
    return f"chunks__{safe_strategy}__{safe_embed}"


@dataclass(frozen=True)
class SearchHit:
    """One search result from dense or sparse query."""

    point_id: str
    score: float
    payload: dict[str, Any]


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


def payload_matches_filters(
    payload: Mapping[str, Any],
    filters: Mapping[str, Any] | None,
) -> bool:
    """Apply store-level filters (doc_id / version / active_versions)."""
    if not filters:
        return True
    if "doc_id" in filters and payload.get("doc_id") != filters["doc_id"]:
        return False
    if "version" in filters and payload.get("version") != filters["version"]:
        return False
    if "doc_ids" in filters:
        allowed = filters["doc_ids"]
        if payload.get("doc_id") not in allowed:
            return False
    if "active_versions" in filters:
        active = filters["active_versions"]
        doc_id = payload.get("doc_id")
        if not isinstance(active, Mapping):
            return False
        if doc_id not in active or payload.get("version") != active[doc_id]:
            return False
    return True


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _sparse_dot(
    indices_a: list[int],
    values_a: list[float],
    indices_b: list[int],
    values_b: list[float],
) -> float:
    if not indices_a or not indices_b:
        return 0.0
    b_map = dict(zip(indices_b, values_b, strict=True))
    score = 0.0
    for idx, val in zip(indices_a, values_a, strict=True):
        other = b_map.get(idx)
        if other is not None:
            score += val * other
    return score


@runtime_checkable
class ChunkStore(Protocol):
    """Index operations used by document lifecycle, reconcile, and retrieval."""

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

    def search_dense(
        self,
        vector: list[float],
        limit: int,
        *,
        filters: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Nearest-neighbour search over the named dense vector."""

    def search_sparse(
        self,
        indices: list[int],
        values: list[float],
        limit: int,
        *,
        filters: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Sparse vector search (BM25-style indices/values)."""


@dataclass
class _MemPoint:
    dense: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
    payload: dict[str, Any]


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
        self._points: dict[str, _MemPoint] = {}
        self._ready = False

    def ensure_collection(self) -> None:
        self._ready = True

    def upsert_chunks(self, points: list[ChunkPoint]) -> None:
        self.ensure_collection()
        for point in points:
            dense = list(point.dense_vector) or [0.0] * self.dense_size
            if len(dense) != self.dense_size:
                raise ValueError(f"dense vector length {len(dense)} != {self.dense_size}")
            self._points[point.point_id] = _MemPoint(
                dense=dense,
                sparse_indices=list(point.sparse_indices),
                sparse_values=list(point.sparse_values),
                payload=point.to_payload(),
            )

    def delete_by_doc_id(self, doc_id: str) -> None:
        self.ensure_collection()
        drop = [
            pid
            for pid, mp in self._points.items()
            if mp.payload.get("doc_id") == doc_id
        ]
        for pid in drop:
            del self._points[pid]

    def delete_by_doc_version_ne(self, doc_id: str, version: int) -> None:
        self.ensure_collection()
        drop = [
            pid
            for pid, mp in self._points.items()
            if mp.payload.get("doc_id") == doc_id and mp.payload.get("version") != version
        ]
        for pid in drop:
            del self._points[pid]

    def list_point_ids_for_doc(self, doc_id: str) -> list[str]:
        self.ensure_collection()
        return [
            pid
            for pid, mp in self._points.items()
            if mp.payload.get("doc_id") == doc_id
        ]

    def get_payloads(self, point_ids: list[str]) -> dict[str, dict[str, Any]]:
        self.ensure_collection()
        out: dict[str, dict[str, Any]] = {}
        for pid in point_ids:
            item = self._points.get(pid)
            if item is not None:
                out[pid] = dict(item.payload)
        return out

    def count_for_doc(self, doc_id: str, *, version: int | None = None) -> int:
        self.ensure_collection()
        count = 0
        for mp in self._points.values():
            if mp.payload.get("doc_id") != doc_id:
                continue
            if version is not None and mp.payload.get("version") != version:
                continue
            count += 1
        return count

    def search_dense(
        self,
        vector: list[float],
        limit: int,
        *,
        filters: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        self.ensure_collection()
        scored: list[SearchHit] = []
        for pid, mp in self._points.items():
            if not payload_matches_filters(mp.payload, filters):
                continue
            score = _cosine_similarity(vector, mp.dense)
            scored.append(SearchHit(point_id=pid, score=score, payload=dict(mp.payload)))
        scored.sort(key=lambda h: (-h.score, h.point_id))
        return scored[: max(0, limit)]

    def search_sparse(
        self,
        indices: list[int],
        values: list[float],
        limit: int,
        *,
        filters: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        self.ensure_collection()
        scored: list[SearchHit] = []
        for pid, mp in self._points.items():
            if not payload_matches_filters(mp.payload, filters):
                continue
            score = _sparse_dot(indices, values, mp.sparse_indices, mp.sparse_values)
            if score <= 0.0:
                continue
            scored.append(SearchHit(point_id=pid, score=score, payload=dict(mp.payload)))
        scored.sort(key=lambda h: (-h.score, h.point_id))
        return scored[: max(0, limit)]


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
        if self.collection not in names:
            vectors_config: dict[str, Any] = {
                DENSE_VECTOR_NAME: qmodels.VectorParams(
                    size=self.dense_size,
                    distance=qmodels.Distance.COSINE,
                )
            }
            sparse_config: dict[str, Any] | None = None
            if self.enable_sparse:
                # IDF modifier: server-side IDF over our custom BM25 TF weights.
                sparse_kwargs: dict[str, Any] = {
                    "index": qmodels.SparseIndexParams(on_disk=False),
                }
                try:
                    from qdrant_client.http.models import Modifier

                    sparse_kwargs["modifier"] = Modifier.IDF
                except Exception:  # noqa: BLE001
                    pass
                sparse_config = {
                    SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(**sparse_kwargs)
                }
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=vectors_config,
                sparse_vectors_config=sparse_config,
            )
        self._ensure_payload_indexes()

    def _ensure_payload_indexes(self) -> None:
        """Idempotent payload indexes used by filters / lifecycle."""
        import logging

        from qdrant_client.http import models as qmodels

        log = logging.getLogger(__name__)
        for field_name, schema in (
            ("doc_id", qmodels.PayloadSchemaType.KEYWORD),
            ("version", qmodels.PayloadSchemaType.INTEGER),
            ("source_type", qmodels.PayloadSchemaType.KEYWORD),
            ("origin", qmodels.PayloadSchemaType.KEYWORD),
            ("doc_date", qmodels.PayloadSchemaType.KEYWORD),
        ):
            try:
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema=schema,
                )
            except Exception:  # noqa: BLE001 — already exists / older cluster
                log.debug("payload_index_skip field=%s", field_name, exc_info=True)

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

    def _build_query_filter(self, filters: Mapping[str, Any] | None) -> Any | None:
        from qdrant_client.http import models as qmodels

        if not filters:
            return None
        must: list[Any] = []
        should: list[Any] = []
        if "doc_id" in filters:
            must.append(
                qmodels.FieldCondition(
                    key="doc_id",
                    match=qmodels.MatchValue(value=filters["doc_id"]),
                )
            )
        if "version" in filters:
            must.append(
                qmodels.FieldCondition(
                    key="version",
                    match=qmodels.MatchValue(value=filters["version"]),
                )
            )
        if "doc_ids" in filters:
            for doc_id in filters["doc_ids"]:
                should.append(
                    qmodels.FieldCondition(
                        key="doc_id",
                        match=qmodels.MatchValue(value=doc_id),
                    )
                )
        if "active_versions" in filters:
            active = filters["active_versions"]
            if isinstance(active, Mapping):
                for doc_id, version in active.items():
                    should.append(
                        qmodels.Filter(
                            must=[
                                qmodels.FieldCondition(
                                    key="doc_id",
                                    match=qmodels.MatchValue(value=doc_id),
                                ),
                                qmodels.FieldCondition(
                                    key="version",
                                    match=qmodels.MatchValue(value=version),
                                ),
                            ]
                        )
                    )
        if not must and not should:
            return None
        kwargs: dict[str, Any] = {}
        if must:
            kwargs["must"] = must
        if should:
            # OR across doc_ids / (doc_id, version) pairs
            kwargs["min_should"] = qmodels.MinShould(conditions=should, min_count=1)
        return qmodels.Filter(**kwargs)

    def search_dense(
        self,
        vector: list[float],
        limit: int,
        *,
        filters: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        self.ensure_collection()
        if limit <= 0:
            return []
        response = self.client.query_points(
            collection_name=self.collection,
            query=list(vector),
            using=DENSE_VECTOR_NAME,
            query_filter=self._build_query_filter(filters),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        hits: list[SearchHit] = []
        for point in response.points:
            hits.append(
                SearchHit(
                    point_id=str(point.id),
                    score=float(point.score),
                    payload=dict(point.payload or {}),
                )
            )
        return hits

    def search_sparse(
        self,
        indices: list[int],
        values: list[float],
        limit: int,
        *,
        filters: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        from qdrant_client.http import models as qmodels

        self.ensure_collection()
        if limit <= 0 or not indices:
            return []
        response = self.client.query_points(
            collection_name=self.collection,
            query=qmodels.SparseVector(indices=list(indices), values=list(values)),
            using=SPARSE_VECTOR_NAME,
            query_filter=self._build_query_filter(filters),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        hits: list[SearchHit] = []
        for point in response.points:
            hits.append(
                SearchHit(
                    point_id=str(point.id),
                    score=float(point.score),
                    payload=dict(point.payload or {}),
                )
            )
        return hits


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
