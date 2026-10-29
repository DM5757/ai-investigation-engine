"""Document CRUD / lifecycle HTTP endpoints."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.api.security import AdminAuth
from app.db.models import DocumentStatus
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.documents import DocumentRepository
from app.deps import DbSession, DocumentLifecycleDep, SettingsDep
from app.errors import NotFound, PayloadTooLarge, UnsupportedFormat
from app.ingestion.lifecycle import LifecycleResult
from app.ingestion.parsers.registry import allowed_extensions, extension_allowed
from app.schemas.documents import (
    ChunkListResponse,
    ChunkOut,
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
    LifecycleResponse,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _lifecycle_response(result: LifecycleResult) -> LifecycleResponse:
    doc = result.document
    return LifecycleResponse(
        outcome=str(result.outcome),
        document_id=doc.id if doc is not None else None,
        status=doc.status if doc is not None else None,
        message=result.message,
        near_duplicate_of=result.near_duplicate_of,
    )


def _summary(doc: object) -> DocumentSummary:
    return DocumentSummary(
        id=doc.id,  # type: ignore[attr-defined]
        external_key=doc.external_key,  # type: ignore[attr-defined]
        filename=doc.filename,  # type: ignore[attr-defined]
        title=doc.title,  # type: ignore[attr-defined]
        status=doc.status,  # type: ignore[attr-defined]
        active_version=doc.active_version,  # type: ignore[attr-defined]
        content_hash=doc.content_hash,  # type: ignore[attr-defined]
        near_duplicate_of=doc.near_duplicate_of,  # type: ignore[attr-defined]
        created_at=doc.created_at,  # type: ignore[attr-defined]
        updated_at=doc.updated_at,  # type: ignore[attr-defined]
        error_message=doc.error_message,  # type: ignore[attr-defined]
    )


def _bump(request: Request, key: str) -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if isinstance(metrics, dict):
        metrics[key] = int(metrics.get(key, 0)) + 1


async def _read_sized(file: UploadFile, max_bytes: int) -> tuple[str, bytes]:
    filename = file.filename or "upload.bin"
    if not extension_allowed(filename):
        allowed = ", ".join(sorted(allowed_extensions()))
        raise UnsupportedFormat(f"extension not allowed; permitted: {allowed}")
    parts: list[bytes] = []
    total = 0
    while True:
        piece = await file.read(65_536)
        if not piece:
            break
        total += len(piece)
        if total > max_bytes:
            raise PayloadTooLarge(f"upload exceeds UPLOAD_MAX_BYTES ({max_bytes})")
        parts.append(piece)
    return os.path.basename(filename), b"".join(parts)


@router.post("", response_model=LifecycleResponse)
async def upload_document(
    request: Request,
    _auth: AdminAuth,
    lifecycle: DocumentLifecycleDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    external_key: Annotated[str | None, Form()] = None,
) -> LifecycleResponse:
    filename, data = await _read_sized(file, settings.upload_max_bytes)
    result = lifecycle.add(filename, data, external_key=external_key or None)
    _bump(request, "uploads")
    return _lifecycle_response(result)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    session: DbSession,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    title_contains: str | None = None,
) -> DocumentListResponse:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    repo = DocumentRepository(session)
    items, total = repo.list_filtered(
        limit=limit,
        offset=offset,
        status=status,
        title_contains=title_contains,
    )
    return DocumentListResponse(
        items=[_summary(d) for d in items],
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str, session: DbSession) -> DocumentDetail:
    doc = DocumentRepository(session).get(document_id)
    if doc is None or doc.status == DocumentStatus.DELETED:
        raise NotFound(f"document {document_id} not found")
    base = _summary(doc)
    return DocumentDetail(**base.model_dump(), metadata=dict(doc.doc_metadata or {}))


@router.get("/{document_id}/chunks", response_model=ChunkListResponse)
def list_chunks(document_id: str, session: DbSession) -> ChunkListResponse:
    doc = DocumentRepository(session).get(document_id)
    if doc is None or doc.status == DocumentStatus.DELETED:
        raise NotFound(f"document {document_id} not found")
    version = doc.active_version
    rows = ChunkRepository(session).list_for_version(document_id, version) if version else []
    items = [
        ChunkOut(
            id=row.id,
            document_id=row.document_id,
            version=row.version,
            chunk_index=row.chunk_index,
            text=row.text,
            heading_path=row.heading_path,
            page=row.page,
            token_count=row.token_count,
            qdrant_point_id=row.qdrant_point_id,
            content_hash=row.content_hash,
        )
        for row in rows
    ]
    return ChunkListResponse(document_id=document_id, version=version or None, items=items)


@router.put("/{document_id}", response_model=LifecycleResponse)
async def update_document(
    document_id: str,
    _auth: AdminAuth,
    lifecycle: DocumentLifecycleDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> LifecycleResponse:
    filename, data = await _read_sized(file, settings.upload_max_bytes)
    result = lifecycle.update_by_id(document_id, filename, data)
    return _lifecycle_response(result)


@router.delete("/{document_id}", response_model=LifecycleResponse)
def delete_document(
    document_id: str,
    _auth: AdminAuth,
    lifecycle: DocumentLifecycleDep,
) -> LifecycleResponse:
    result = lifecycle.delete(document_id)
    return _lifecycle_response(result)


@router.post("/{document_id}/reindex", response_model=LifecycleResponse)
def reindex_document(
    document_id: str,
    _auth: AdminAuth,
    lifecycle: DocumentLifecycleDep,
) -> LifecycleResponse:
    result = lifecycle.reindex(document_id)
    return _lifecycle_response(result)
