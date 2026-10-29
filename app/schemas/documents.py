"""Document API request/response DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LifecycleResponse(BaseModel):
    """Mapped from DocumentLifecycle LifecycleResult."""

    outcome: str
    document_id: str | None = None
    status: str | None = None
    message: str = ""
    near_duplicate_of: str | None = None


class DocumentSummary(BaseModel):
    id: str
    external_key: str | None = None
    filename: str
    title: str
    status: str
    active_version: int
    content_hash: str
    near_duplicate_of: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_message: str | None = None


class DocumentDetail(DocumentSummary):
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    limit: int
    offset: int
    total: int


class ChunkOut(BaseModel):
    id: str
    document_id: str
    version: int
    chunk_index: int
    text: str
    heading_path: str | None = None
    page: int | None = None
    token_count: int = 0
    qdrant_point_id: str
    content_hash: str


class ChunkListResponse(BaseModel):
    document_id: str
    version: int | None
    items: list[ChunkOut]
