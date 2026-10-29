"""Chunk repository helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk


class ChunkRepository:
    """Persistence helpers for document chunks."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_version(self, document_id: str, version: int) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.document_id == document_id, Chunk.version == version)
            .order_by(Chunk.chunk_index)
        )
        return list(self.session.scalars(stmt).all())

    def list_for_document(self, document_id: str) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.version, Chunk.chunk_index)
        )
        return list(self.session.scalars(stmt).all())

    def hashes_for_version(self, document_id: str, version: int) -> dict[str, Chunk]:
        """Map content_hash -> chunk for a version (first wins on collision)."""
        rows = self.list_for_version(document_id, version)
        return {row.content_hash: row for row in rows}

    def add_many(
        self,
        document_id: str,
        version: int,
        rows: list[dict[str, Any]],
    ) -> list[Chunk]:
        created: list[Chunk] = []
        for row in rows:
            chunk = Chunk(
                document_id=document_id,
                version=version,
                chunk_index=int(row["chunk_index"]),
                content_hash=str(row["content_hash"]),
                text=str(row["text"]),
                char_start=int(row.get("char_start", 0)),
                char_end=int(row.get("char_end", 0)),
                heading_path=row.get("heading_path"),
                page=row.get("page"),
                token_count=int(row.get("token_count", 0)),
                strategy=str(row.get("strategy", "structure_aware")),
                qdrant_point_id=str(row["qdrant_point_id"]),
                chunk_metadata=dict(row.get("metadata") or {}),
            )
            self.session.add(chunk)
            created.append(chunk)
        self.session.flush()
        return created

    def delete_version(self, document_id: str, version: int) -> int:
        rows = self.list_for_version(document_id, version)
        for row in rows:
            self.session.delete(row)
        self.session.flush()
        return len(rows)

    def delete_for_document(self, document_id: str) -> int:
        rows = self.list_for_document(document_id)
        for row in rows:
            self.session.delete(row)
        self.session.flush()
        return len(rows)

    def count_all(self) -> int:
        from sqlalchemy import func

        return int(self.session.scalar(select(func.count()).select_from(Chunk)) or 0)

    def get(self, chunk_id: str) -> Chunk | None:
        return self.session.get(Chunk, chunk_id)

    def get_by_point_id(self, point_id: str) -> Chunk | None:
        stmt = select(Chunk).where(Chunk.qdrant_point_id == point_id)
        return self.session.scalars(stmt).first()
