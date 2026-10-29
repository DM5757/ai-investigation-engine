"""documents lifecycle tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("external_key", sa.String(length=512), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("simhash", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("near_duplicate_of", sa.String(length=36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["near_duplicate_of"], ["documents.id"]),
    )
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.execute(
        "CREATE UNIQUE INDEX uq_documents_external_key_active "
        "ON documents (external_key) WHERE status != 'DELETED'"
    )

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("simhash", sa.String(length=16), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "version", name="uq_document_versions_doc_version"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.String(length=1024), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("qdrant_point_id", sa.String(length=36), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "document_id",
            "version",
            "chunk_index",
            name="uq_chunks_doc_version_index",
        ),
    )
    op.create_index("ix_chunks_content_hash", "chunks", ["content_hash"])
    op.create_index("ix_chunks_doc_version", "chunks", ["document_id", "version"])

    op.create_table(
        "simhash_bands",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("band_index", sa.Integer(), nullable=False),
        sa.Column("band_value", sa.Integer(), nullable=False),
        sa.Column("simhash", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "band_index", name="uq_simhash_bands_doc_band"),
    )
    op.create_index("ix_simhash_bands_document_id", "simhash_bands", ["document_id"])
    op.create_index("ix_simhash_bands_band", "simhash_bands", ["band_index", "band_value"])

    op.create_table(
        "index_stats",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("collection_name", sa.String(length=256), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reconcile_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("collection_name"),
    )


def downgrade() -> None:
    op.drop_table("index_stats")
    op.drop_table("simhash_bands")
    op.drop_table("chunks")
    op.drop_table("document_versions")
    op.drop_index("uq_documents_external_key_active", table_name="documents")
    op.drop_table("documents")
