"""Document / version / simhash band repository helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentStatus, DocumentVersion, IndexStats, SimhashBand


class DocumentRepository:
    """CRUD helpers for documents and related dedup tables."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, document_id: str) -> Document | None:
        return self.session.get(Document, document_id)

    def get_by_external_key(self, external_key: str) -> Document | None:
        stmt = select(Document).where(
            Document.external_key == external_key,
            Document.status != DocumentStatus.DELETED,
        )
        return self.session.scalars(stmt).first()

    def find_by_content_hash(
        self,
        content_hash: str,
        *,
        exclude_id: str | None = None,
    ) -> Document | None:
        stmt = select(Document).where(
            Document.content_hash == content_hash,
            Document.status.notin_([DocumentStatus.DELETED, DocumentStatus.FAILED]),
        )
        if exclude_id is not None:
            stmt = stmt.where(Document.id != exclude_id)
        return self.session.scalars(stmt).first()

    def list_by_status(self, *statuses: str) -> list[Document]:
        stmt = select(Document).where(Document.status.in_(statuses))
        return list(self.session.scalars(stmt).all())

    def create(
        self,
        *,
        external_key: str | None,
        filename: str,
        title: str,
        content_hash: str,
        simhash: str,
        status: str = DocumentStatus.PENDING,
        active_version: int = 0,
        near_duplicate_of: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        doc = Document(
            external_key=external_key,
            filename=filename,
            title=title,
            content_hash=content_hash,
            simhash=simhash,
            status=status,
            active_version=active_version,
            near_duplicate_of=near_duplicate_of,
            doc_metadata=metadata or {},
        )
        self.session.add(doc)
        self.session.flush()
        return doc

    def add_version(
        self,
        document: Document,
        *,
        version: int,
        content_hash: str,
        text: str,
        title: str,
        simhash: str,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentVersion:
        row = DocumentVersion(
            document_id=document.id,
            version=version,
            content_hash=content_hash,
            text=text,
            title=title,
            simhash=simhash,
            version_metadata=metadata or {},
        )
        self.session.add(row)
        self.session.flush()
        return row

    def replace_simhash_bands(
        self,
        document_id: str,
        *,
        bands: list[int],
        simhash: str,
        content_hash: str,
    ) -> None:
        existing = self.session.scalars(
            select(SimhashBand).where(SimhashBand.document_id == document_id)
        ).all()
        for row in existing:
            self.session.delete(row)
        self.session.flush()
        for idx, value in enumerate(bands):
            self.session.add(
                SimhashBand(
                    document_id=document_id,
                    band_index=idx,
                    band_value=value,
                    simhash=simhash,
                    content_hash=content_hash,
                )
            )
        self.session.flush()

    def candidates_by_bands(
        self,
        bands: list[int],
        *,
        exclude_id: str | None = None,
    ) -> list[Document]:
        """Return ACTIVE documents sharing any LSH band value."""
        if not bands:
            return []
        doc_ids: set[str] = set()
        for idx, value in enumerate(bands):
            stmt = select(SimhashBand.document_id).where(
                SimhashBand.band_index == idx,
                SimhashBand.band_value == value,
            )
            doc_ids.update(self.session.scalars(stmt).all())
        if exclude_id is not None:
            doc_ids.discard(exclude_id)
        if not doc_ids:
            return []
        doc_stmt = select(Document).where(
            Document.id.in_(doc_ids),
            Document.status == DocumentStatus.ACTIVE,
        )
        return list(self.session.scalars(doc_stmt).all())

    def set_status(
        self,
        document: Document,
        status: str,
        *,
        error_message: str | None = None,
        clear_error: bool = False,
    ) -> None:
        document.status = status
        document.updated_at = datetime.now(UTC)
        if clear_error:
            document.error_message = None
        elif error_message is not None:
            document.error_message = error_message
        if status == DocumentStatus.DELETED:
            document.deleted_at = datetime.now(UTC)
        self.session.flush()

    def set_active_version(self, document: Document, version: int) -> None:
        document.active_version = version
        document.updated_at = datetime.now(UTC)
        self.session.flush()

    def upsert_index_stats(
        self,
        collection_name: str,
        *,
        document_count: int,
        chunk_count: int,
        reconcile: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> IndexStats:
        stmt = select(IndexStats).where(IndexStats.collection_name == collection_name)
        stats = self.session.scalars(stmt).first()
        if stats is None:
            stats = IndexStats(
                collection_name=collection_name,
                document_count=document_count,
                chunk_count=chunk_count,
                stats_metadata=metadata or {},
            )
            self.session.add(stats)
        else:
            stats.document_count = document_count
            stats.chunk_count = chunk_count
            if metadata is not None:
                stats.stats_metadata = metadata
        if reconcile:
            stats.last_reconcile_at = datetime.now(UTC)
        self.session.flush()
        return stats
