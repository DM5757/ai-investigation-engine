"""Reconcile Postgres document state with the Qdrant chunk index."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models import Document, DocumentStatus
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.documents import DocumentRepository
from app.index.qdrant_store import ChunkPoint, ChunkStore
from app.ingestion.lifecycle import zero_embed

logger = logging.getLogger(__name__)


@dataclass
class ReconcileReport:
    activated: list[str] = field(default_factory=list)
    cleaned_versions: list[str] = field(default_factory=list)
    finished_deletes: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def reconcile_session(session: Session, store: ChunkStore) -> ReconcileReport:
    """Bring INDEXING/DELETING docs and stale Qdrant versions into sync."""
    report = ReconcileReport()
    docs = DocumentRepository(session)
    chunks = ChunkRepository(session)
    store.ensure_collection()

    for doc in docs.list_by_status(DocumentStatus.DELETING):
        try:
            store.delete_by_doc_id(doc.id)
            docs.set_status(doc, DocumentStatus.DELETED)
            session.commit()
            report.finished_deletes.append(doc.id)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception("reconcile delete failed for %s", doc.id)
            failed_doc = docs.get(doc.id)
            if failed_doc is not None:
                docs.set_status(failed_doc, DocumentStatus.FAILED, error_message=str(exc))
                session.commit()
                report.failed.append(failed_doc.id)
            else:
                report.failed.append(doc.id)

    for doc in docs.list_by_status(DocumentStatus.INDEXING, DocumentStatus.PENDING):
        try:
            _complete_indexing(session, docs, chunks, store, doc, report)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception("reconcile indexing failed for %s", doc.id)
            failed_doc = docs.get(doc.id)
            if failed_doc is not None:
                docs.set_status(failed_doc, DocumentStatus.FAILED, error_message=str(exc))
                session.commit()
                report.failed.append(failed_doc.id)
            else:
                report.failed.append(doc.id)

    for doc in docs.list_by_status(DocumentStatus.ACTIVE):
        try:
            store.delete_by_doc_version_ne(doc.id, doc.active_version)
            report.cleaned_versions.append(doc.id)
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception("reconcile version cleanup failed for %s", doc.id)
            report.notes.append(f"{doc.id}: cleanup error {exc}")

    active = docs.list_by_status(DocumentStatus.ACTIVE)
    chunk_count = 0
    for doc in active:
        chunk_count += len(chunks.list_for_version(doc.id, doc.active_version))
    docs.upsert_index_stats(
        store.collection,
        document_count=len(active),
        chunk_count=chunk_count,
        reconcile=True,
    )
    session.commit()
    return report


def _complete_indexing(
    session: Session,
    docs: DocumentRepository,
    chunks: ChunkRepository,
    store: ChunkStore,
    doc: Document,
    report: ReconcileReport,
) -> None:
    versions = sorted({c.version for c in chunks.list_for_document(doc.id)})
    if not versions:
        docs.set_status(doc, DocumentStatus.FAILED, error_message="no chunks to index")
        session.commit()
        report.failed.append(doc.id)
        return

    target = max(versions)
    rows = chunks.list_for_version(doc.id, target)
    point_ids = [r.qdrant_point_id for r in rows]
    existing = store.get_payloads(point_ids)
    missing = [r for r in rows if r.qdrant_point_id not in existing]
    if missing:
        vectors = zero_embed([r.text for r in missing])
        points = [
            ChunkPoint(
                point_id=row.qdrant_point_id,
                doc_id=doc.id,
                version=target,
                chunk_index=row.chunk_index,
                content_hash=row.content_hash,
                text=row.text,
                dense_vector=dense,
            )
            for row, dense in zip(missing, vectors, strict=True)
        ]
        store.upsert_chunks(points)

    docs.set_active_version(doc, target)
    docs.set_status(doc, DocumentStatus.ACTIVE, clear_error=True)
    session.commit()
    store.delete_by_doc_version_ne(doc.id, target)
    report.activated.append(doc.id)
