"""SQLAlchemy ORM models (Phase 1 health + Phase 2 document lifecycle)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class HealthProbe(Base):
    """Tiny table used to verify Alembic + DB connectivity in Phase 1."""

    __tablename__ = "health_probes"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    note: Mapped[str] = mapped_column(Text, default="ok")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class DocumentStatus:
    """Document lifecycle states."""

    PENDING = "PENDING"
    INDEXING = "INDEXING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    DELETING = "DELETING"
    DELETED = "DELETED"

    ALL = (PENDING, INDEXING, ACTIVE, FAILED, DELETING, DELETED)


class Document(Base):
    """Logical document identity with soft-delete and active version pointer."""

    __tablename__ = "documents"
    __table_args__ = (
        Index(
            "uq_documents_external_key_active",
            "external_key",
            unique=True,
            sqlite_where=text("status != 'DELETED'"),
            postgresql_where=text("status != 'DELETED'"),
        ),
        Index("ix_documents_content_hash", "content_hash"),
        Index("ix_documents_status", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    external_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    simhash: Mapped[str] = mapped_column(String(16), nullable=False, default="0")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentStatus.PENDING)
    active_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    near_duplicate_of: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("documents.id"),
        nullable=True,
    )
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    versions: Mapped[list[DocumentVersion]] = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentVersion(Base):
    """Immutable snapshot of a document at a version number."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_versions_doc_version"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    simhash: Mapped[str] = mapped_column(String(16), nullable=False, default="0")
    version_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document: Mapped[Document] = relationship("Document", back_populates="versions")


class Chunk(Base):
    """Chunk row stored in Postgres/SQLite; Qdrant holds vectors + payload."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version",
            "chunk_index",
            name="uq_chunks_doc_version_index",
        ),
        Index("ix_chunks_content_hash", "content_hash"),
        Index("ix_chunks_doc_version", "document_id", "version"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heading_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, default="structure_aware")
    qdrant_point_id: Mapped[str] = mapped_column(String(36), nullable=False)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document: Mapped[Document] = relationship("Document", back_populates="chunks")


class SimhashBand(Base):
    """LSH band entry for near-duplicate candidate generation."""

    __tablename__ = "simhash_bands"
    __table_args__ = (
        Index("ix_simhash_bands_band", "band_index", "band_value"),
        UniqueConstraint(
            "document_id",
            "band_index",
            name="uq_simhash_bands_doc_band",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    band_index: Mapped[int] = mapped_column(Integer, nullable=False)
    band_value: Mapped[int] = mapped_column(Integer, nullable=False)
    simhash: Mapped[str] = mapped_column(String(16), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class IndexStats(Base):
    """Per-collection index counters and reconcile bookkeeping."""

    __tablename__ = "index_stats"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    collection_name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reconcile_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    stats_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
