"""Document add / update / delete lifecycle with Qdrant sync."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Document, DocumentStatus
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.documents import DocumentRepository
from app.errors import DuplicateDocument, NotFound
from app.index.qdrant_store import ChunkPoint, ChunkStore
from app.ingestion.dedup.simhash import find_near_duplicates
from app.ingestion.pipeline import PreparedDocument, prepare_document
from app.retrieval.bm25_sparse import Bm25Encoder

logger = logging.getLogger(__name__)

EmbedFn = Callable[[Sequence[str]], list[list[float]]]


class LifecycleOutcome(StrEnum):
    CREATED = "created"
    UNCHANGED = "unchanged"
    UPDATED = "updated"
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    SKIPPED_NEAR_DUPLICATE = "skipped_near_duplicate"
    DELETED = "deleted"
    FAILED = "failed"


@dataclass
class LifecycleResult:
    outcome: LifecycleOutcome
    document: Document | None
    message: str = ""
    near_duplicate_of: str | None = None


def zero_embed(texts: Sequence[str], *, dims: int = 384) -> list[list[float]]:
    """Phase-2 placeholder embeddings (no FastEmbed / LLM)."""
    return [[0.0] * dims for _ in texts]


class DocumentLifecycle:
    """Orchestrates parse/dedup/persist/index transitions."""

    def __init__(
        self,
        session: Session,
        store: ChunkStore,
        *,
        chunk_strategy: str = "structure_aware",
        simhash_threshold: int = 3,
        near_duplicate_policy: str = "flag",
        embed_fn: EmbedFn | None = None,
        sparse_encoder: Bm25Encoder | None = None,
        dense_dims: int = 384,
        stop_before_active: bool = False,
        stop_before_version_cleanup: bool = False,
    ) -> None:
        self.session = session
        self.store = store
        self.docs = DocumentRepository(session)
        self.chunks = ChunkRepository(session)
        self.chunk_strategy = chunk_strategy
        self.simhash_threshold = simhash_threshold
        self.near_duplicate_policy = near_duplicate_policy
        self.embed_fn = embed_fn or (lambda texts: zero_embed(texts, dims=dense_dims))
        self.sparse_encoder = sparse_encoder
        self.dense_dims = dense_dims
        # Test hooks to simulate crash windows for reconcile.
        self.stop_before_active = stop_before_active
        self.stop_before_version_cleanup = stop_before_version_cleanup

    def add(
        self,
        filename: str,
        data: bytes,
        *,
        external_key: str | None = None,
        prepared: PreparedDocument | None = None,
        parse_fn: Callable[[str, bytes], Any] | None = None,
        normalize_fn: Callable[[str], str] | None = None,
        chunk_fn: Callable[..., Any] | None = None,
    ) -> LifecycleResult:
        """Ingest a new document (or no-op / reject duplicates)."""
        try:
            prep = prepared or prepare_document(
                filename,
                data,
                chunk_strategy=self.chunk_strategy,
                parse_fn=parse_fn,
                normalize_fn=normalize_fn,
                chunk_fn=chunk_fn,
            )
            if external_key:
                existing = self.docs.get_by_external_key(external_key)
                if existing is not None:
                    if existing.content_hash == prep.content_hash:
                        return LifecycleResult(
                            LifecycleOutcome.UNCHANGED,
                            existing,
                            "same external_key and content_hash",
                        )
                    return self._update_existing(existing, prep)

            exact = self.docs.find_by_content_hash(prep.content_hash)
            if exact is not None and (external_key is None or exact.external_key != external_key):
                return LifecycleResult(
                    LifecycleOutcome.EXACT_DUPLICATE,
                    exact,
                    "exact content_hash already indexed",
                    near_duplicate_of=exact.id,
                )

            near_of = self._near_duplicate_target(prep)
            if near_of is not None and self.near_duplicate_policy == "skip":
                return LifecycleResult(
                    LifecycleOutcome.SKIPPED_NEAR_DUPLICATE,
                    None,
                    "near-duplicate skipped by policy",
                    near_duplicate_of=near_of,
                )

            doc = self.docs.create(
                external_key=external_key,
                filename=prep.filename,
                title=prep.title,
                content_hash=prep.content_hash,
                simhash=f"{prep.simhash:016x}",
                status=DocumentStatus.PENDING,
                active_version=0,
                near_duplicate_of=near_of,
                metadata=prep.metadata,
            )
            version = 1
            self._persist_version_and_chunks(doc, version, prep)
            self.docs.replace_simhash_bands(
                doc.id,
                bands=prep.bands,
                simhash=f"{prep.simhash:016x}",
                content_hash=prep.content_hash,
            )
            self.session.commit()
        except DuplicateDocument:
            raise
        except Exception as exc:  # noqa: BLE001 — lifecycle must mark FAILED
            logger.exception("document add failed before index")
            self.session.rollback()
            return LifecycleResult(LifecycleOutcome.FAILED, None, str(exc))

        try:
            self._index_version(doc, version)
            if self.stop_before_active:
                return LifecycleResult(
                    LifecycleOutcome.CREATED,
                    doc,
                    "stopped before ACTIVE (simulated crash)",
                    near_duplicate_of=near_of,
                )

            self.docs.set_status(doc, DocumentStatus.ACTIVE, clear_error=True)
            self.docs.set_active_version(doc, version)
            self.session.commit()

            outcome = (
                LifecycleOutcome.NEAR_DUPLICATE
                if near_of is not None
                else LifecycleOutcome.CREATED
            )
            return LifecycleResult(outcome, doc, near_duplicate_of=near_of)
        except Exception as exc:  # noqa: BLE001
            logger.exception("document indexing failed")
            self.session.rollback()
            failed = self.docs.get(doc.id)
            if failed is not None:
                self.docs.set_status(failed, DocumentStatus.FAILED, error_message=str(exc))
                self.session.commit()
            return LifecycleResult(LifecycleOutcome.FAILED, failed, str(exc))

    def update(
        self,
        external_key: str,
        filename: str,
        data: bytes,
        *,
        prepared: PreparedDocument | None = None,
        parse_fn: Callable[[str, bytes], Any] | None = None,
        normalize_fn: Callable[[str], str] | None = None,
        chunk_fn: Callable[..., Any] | None = None,
    ) -> LifecycleResult:
        existing = self.docs.get_by_external_key(external_key)
        if existing is None:
            raise NotFound(f"document with external_key={external_key!r} not found")
        prep = prepared or prepare_document(
            filename,
            data,
            chunk_strategy=self.chunk_strategy,
            parse_fn=parse_fn,
            normalize_fn=normalize_fn,
            chunk_fn=chunk_fn,
        )
        if existing.content_hash == prep.content_hash:
            return LifecycleResult(
                LifecycleOutcome.UNCHANGED,
                existing,
                "same external_key and content_hash",
            )
        return self._update_existing(existing, prep)

    def update_by_id(
        self,
        document_id: str,
        filename: str,
        data: bytes,
        *,
        prepared: PreparedDocument | None = None,
        parse_fn: Callable[[str, bytes], Any] | None = None,
        normalize_fn: Callable[[str], str] | None = None,
        chunk_fn: Callable[..., Any] | None = None,
    ) -> LifecycleResult:
        """Replace content for an existing document id (new version)."""
        existing = self.docs.get(document_id)
        if existing is None or existing.status == DocumentStatus.DELETED:
            raise NotFound(f"document {document_id} not found")
        prep = prepared or prepare_document(
            filename,
            data,
            chunk_strategy=self.chunk_strategy,
            parse_fn=parse_fn,
            normalize_fn=normalize_fn,
            chunk_fn=chunk_fn,
        )
        if existing.content_hash == prep.content_hash:
            return LifecycleResult(
                LifecycleOutcome.UNCHANGED,
                existing,
                "same content_hash",
            )
        return self._update_existing(existing, prep)

    def reindex(self, document_id: str) -> LifecycleResult:
        """Re-embed and upsert the active version into the chunk store."""
        doc = self.docs.get(document_id)
        if doc is None or doc.status == DocumentStatus.DELETED:
            raise NotFound(f"document {document_id} not found")
        if doc.active_version < 1:
            return LifecycleResult(
                LifecycleOutcome.FAILED,
                doc,
                "document has no active version to reindex",
            )
        try:
            self._index_version(doc, doc.active_version)
            self.docs.set_status(doc, DocumentStatus.ACTIVE, clear_error=True)
            self.session.commit()
            return LifecycleResult(LifecycleOutcome.UPDATED, doc, "reindexed active version")
        except Exception as exc:  # noqa: BLE001
            logger.exception("document reindex failed")
            self.session.rollback()
            failed = self.docs.get(document_id)
            if failed is not None:
                self.docs.set_status(failed, DocumentStatus.FAILED, error_message=str(exc))
                self.session.commit()
            return LifecycleResult(LifecycleOutcome.FAILED, failed, str(exc))

    def delete(self, document_id: str) -> LifecycleResult:
        doc = self.docs.get(document_id)
        if doc is None or doc.status == DocumentStatus.DELETED:
            raise NotFound(f"document {document_id} not found")
        try:
            self.docs.set_status(doc, DocumentStatus.DELETING, clear_error=True)
            self.session.commit()
            self.store.delete_by_doc_id(doc.id)
            self.docs.set_status(doc, DocumentStatus.DELETED)
            self.session.commit()
            return LifecycleResult(LifecycleOutcome.DELETED, doc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("document delete failed")
            self.session.rollback()
            doc = self.docs.get(document_id)
            if doc is not None:
                self.docs.set_status(doc, DocumentStatus.FAILED, error_message=str(exc))
                self.session.commit()
            return LifecycleResult(LifecycleOutcome.FAILED, doc, str(exc))

    def _update_existing(self, existing: Document, prep: PreparedDocument) -> LifecycleResult:
        try:
            new_version = existing.active_version + 1
            if new_version < 1:
                new_version = 1

            existing.filename = prep.filename
            existing.title = prep.title
            existing.content_hash = prep.content_hash
            existing.simhash = f"{prep.simhash:016x}"
            existing.doc_metadata = prep.metadata
            self.docs.set_status(existing, DocumentStatus.PENDING, clear_error=True)

            prev_hashes = self.chunks.hashes_for_version(existing.id, existing.active_version)
            self._persist_version_and_chunks(existing, new_version, prep)
            self.docs.replace_simhash_bands(
                existing.id,
                bands=prep.bands,
                simhash=f"{prep.simhash:016x}",
                content_hash=prep.content_hash,
            )
            self.session.commit()

            # Diff by chunk content_hash: upsert only new/changed chunks.
            changed_rows = [
                (chunk, chash)
                for chunk, chash in zip(prep.chunks, prep.chunk_hashes, strict=True)
                if chash not in prev_hashes
            ]
            # Always upsert all new-version points so version filter is correct;
            # unchanged text still needs new point ids for the new version.
            self._index_version(existing, new_version)

            if self.stop_before_version_cleanup:
                self.docs.set_active_version(existing, new_version)
                self.docs.set_status(existing, DocumentStatus.INDEXING)
                self.session.commit()
                return LifecycleResult(
                    LifecycleOutcome.UPDATED,
                    existing,
                    "stopped before Qdrant version cleanup (simulated crash)",
                )

            self.docs.set_active_version(existing, new_version)
            self.session.commit()
            self.store.delete_by_doc_version_ne(existing.id, new_version)
            self.docs.set_status(existing, DocumentStatus.ACTIVE, clear_error=True)
            self.session.commit()
            _ = changed_rows
            return LifecycleResult(LifecycleOutcome.UPDATED, existing)
        except Exception as exc:  # noqa: BLE001
            logger.exception("document update failed")
            self.session.rollback()
            doc = self.docs.get(existing.id)
            if doc is not None:
                self.docs.set_status(doc, DocumentStatus.FAILED, error_message=str(exc))
                self.session.commit()
            return LifecycleResult(LifecycleOutcome.FAILED, doc, str(exc))

    def _near_duplicate_target(self, prep: PreparedDocument) -> str | None:
        candidates = self.docs.candidates_by_bands(prep.bands)
        pairs = [(c.id, int(c.simhash, 16)) for c in candidates]
        hits = find_near_duplicates(prep.simhash, pairs, threshold=self.simhash_threshold)
        if not hits:
            return None
        return hits[0][0]

    def _persist_version_and_chunks(
        self,
        doc: Document,
        version: int,
        prep: PreparedDocument,
    ) -> None:
        self.docs.add_version(
            doc,
            version=version,
            content_hash=prep.content_hash,
            text=prep.text,
            title=prep.title,
            simhash=f"{prep.simhash:016x}",
            metadata=prep.metadata,
        )
        rows: list[dict[str, Any]] = []
        for chunk, chash in zip(prep.chunks, prep.chunk_hashes, strict=True):
            point_id = str(uuid.uuid4())
            rows.append(
                {
                    "chunk_index": chunk.chunk_index,
                    "content_hash": chash,
                    "text": chunk.text,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "heading_path": chunk.heading_path,
                    "page": chunk.page,
                    "token_count": chunk.token_count,
                    "strategy": chunk.strategy or self.chunk_strategy,
                    "qdrant_point_id": point_id,
                    "metadata": {
                        "context_header": getattr(chunk, "context_header", None),
                    },
                }
            )
        self.chunks.add_many(doc.id, version, rows)

    def _index_version(self, doc: Document, version: int) -> None:
        self.docs.set_status(doc, DocumentStatus.INDEXING, clear_error=True)
        self.session.commit()
        rows = self.chunks.list_for_version(doc.id, version)
        vectors = self.embed_fn([r.text for r in rows])
        points: list[ChunkPoint] = []
        for row, dense in zip(rows, vectors, strict=True):
            sparse_indices: list[int] = []
            sparse_values: list[float] = []
            if self.sparse_encoder is not None:
                sparse = self.sparse_encoder.encode_document(row.text)
                sparse_indices = sparse.indices
                sparse_values = sparse.values
            heading = row.heading_path
            points.append(
                ChunkPoint(
                    point_id=row.qdrant_point_id,
                    doc_id=doc.id,
                    version=version,
                    chunk_index=row.chunk_index,
                    content_hash=row.content_hash,
                    text=row.text,
                    dense_vector=dense,
                    sparse_indices=sparse_indices,
                    sparse_values=sparse_values,
                    payload_extra={
                        "title": doc.title,
                        "heading_path": heading,
                        "near_duplicate_of": doc.near_duplicate_of,
                    },
                )
            )
        self.store.upsert_chunks(points)
