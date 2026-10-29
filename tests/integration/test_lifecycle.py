"""Integration tests for document lifecycle + Qdrant reconcile."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.models import Base, DocumentStatus
from app.db.session import get_engine, get_session_factory
from app.index.qdrant_store import ChunkStore, InMemoryChunkStore, make_local_chunk_store
from app.ingestion.chunking.base import Chunk
from app.ingestion.dedup.hashing import chunk_content_hash, content_hash
from app.ingestion.dedup.simhash import band_values, compute_simhash
from app.ingestion.lifecycle import DocumentLifecycle, LifecycleOutcome
from app.ingestion.normalize import normalize_text
from app.ingestion.parsers.base import ParsedDocument, Span
from app.ingestion.pipeline import PreparedDocument
from app.ingestion.reconcile import reconcile_session


@dataclass
class FakeParsedDocument:
    """Stand-in when real parsers are unavailable."""

    text: str
    title: str = "fake"
    metadata: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)


def _fake_parse(filename: str, data: bytes) -> ParsedDocument:
    text = data.decode("utf-8")
    return ParsedDocument(
        text=text,
        title=filename,
        metadata={"source": "fake"},
        spans=[Span(0, len(text))] if text else [],
    )


def _chunk_fn(text: str, *, title: str = "", spans: list[Span] | None = None) -> list[Chunk]:
    _ = title, spans
    if not text:
        return []
    mid = max(1, len(text) // 2)
    parts = [text[:mid], text[mid:]] if len(text) > 40 else [text]
    out: list[Chunk] = []
    cursor = 0
    for i, part in enumerate(parts):
        start = text.find(part, cursor)
        end = start + len(part)
        cursor = end
        out.append(
            Chunk(
                chunk_index=i,
                char_start=start,
                char_end=end,
                text=part,
                heading_path=None,
                page=None,
                token_count=len(part.split()),
                strategy="structure_aware",
            )
        )
    return out


def _prepare(text: str, filename: str = "doc.txt") -> PreparedDocument:
    norm = normalize_text(text)
    fp = compute_simhash(norm)
    chunks = _chunk_fn(norm)
    return PreparedDocument(
        filename=filename,
        title=filename,
        text=norm,
        content_hash=content_hash(norm),
        simhash=fp,
        bands=band_values(fp),
        chunks=chunks,
        chunk_hashes=[chunk_content_hash(c.text) for c in chunks],
        metadata={"source": "fake"},
        spans=[Span(0, len(norm))] if norm else [],
    )


@pytest.fixture()
def db_session() -> Iterator[Session]:
    url = "sqlite+pysqlite:///:memory:"
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    factory = get_session_factory(url)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        get_engine.cache_clear()
        get_session_factory.cache_clear()


@pytest.fixture()
def store() -> ChunkStore:
    # Prefer embedded Qdrant; fall back when native gRPC DLLs are blocked (WDAC).
    try:
        return make_local_chunk_store(strategy="structure_aware", embedding_short="bge-small")
    except Exception:  # noqa: BLE001
        return InMemoryChunkStore(strategy="structure_aware", embedding_short="bge-small")


@pytest.fixture()
def life(db_session: Session, store: ChunkStore) -> DocumentLifecycle:
    return DocumentLifecycle(
        db_session,
        store,
        chunk_strategy="structure_aware",
        simhash_threshold=3,
        near_duplicate_policy="flag",
    )


BASE_TEXT = ("the quick brown fox jumps over the lazy dog " * 8).strip()
NEAR_TEXT = BASE_TEXT.replace("lazy dog", "lazy dogs", 1)


def test_add_reaches_active(life: DocumentLifecycle, store: ChunkStore) -> None:
    prep = _prepare(BASE_TEXT)
    result = life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=prep)
    assert result.outcome == LifecycleOutcome.CREATED
    assert result.document is not None
    assert result.document.status == DocumentStatus.ACTIVE
    assert result.document.active_version == 1
    assert store.count_for_doc(result.document.id, version=1) >= 1


def test_same_key_same_hash_unchanged(life: DocumentLifecycle) -> None:
    prep = _prepare(BASE_TEXT)
    first = life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=prep)
    second = life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=prep)
    assert first.outcome == LifecycleOutcome.CREATED
    assert second.outcome == LifecycleOutcome.UNCHANGED
    assert second.document is not None
    assert first.document is not None
    assert second.document.id == first.document.id


def test_different_key_same_hash_exact_duplicate(life: DocumentLifecycle) -> None:
    prep = _prepare(BASE_TEXT)
    first = life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=prep)
    dup = life.add("b.txt", BASE_TEXT.encode(), external_key="k2", prepared=prep)
    assert first.outcome == LifecycleOutcome.CREATED
    assert dup.outcome == LifecycleOutcome.EXACT_DUPLICATE
    assert dup.document is not None
    assert first.document is not None
    assert dup.document.id == first.document.id


def test_near_duplicate_flagged(life: DocumentLifecycle) -> None:
    r1 = life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=_prepare(BASE_TEXT))
    r2 = life.add("b.txt", NEAR_TEXT.encode(), external_key="k2", prepared=_prepare(NEAR_TEXT))
    assert r1.outcome == LifecycleOutcome.CREATED
    assert r2.outcome == LifecycleOutcome.NEAR_DUPLICATE
    assert r2.document is not None
    assert r1.document is not None
    assert r2.document.near_duplicate_of == r1.document.id
    assert r2.document.status == DocumentStatus.ACTIVE


def test_update_versions_and_cleans_old_points(
    life: DocumentLifecycle,
    store: ChunkStore,
) -> None:
    prep = _prepare(BASE_TEXT)
    created = life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=prep)
    assert created.document is not None
    doc_id = created.document.id
    old_ids = store.list_point_ids_for_doc(doc_id)

    updated_text = BASE_TEXT + " additional remediation completed successfully yesterday"
    upd = life.update(
        "k1",
        "a.txt",
        updated_text.encode(),
        prepared=_prepare(updated_text),
    )
    assert upd.outcome == LifecycleOutcome.UPDATED
    assert upd.document is not None
    assert upd.document.active_version == 2
    assert upd.document.status == DocumentStatus.ACTIVE

    payloads = store.get_payloads(store.list_point_ids_for_doc(doc_id))
    assert payloads
    assert all(p.get("version") == 2 for p in payloads.values())
    # Old point ids should be gone (or no longer present for version 1).
    remaining_old = [pid for pid in old_ids if pid in payloads]
    assert remaining_old == []


def test_delete_soft_and_external_key_reusable(
    life: DocumentLifecycle,
    store: ChunkStore,
) -> None:
    prep = _prepare(BASE_TEXT)
    created = life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=prep)
    assert created.document is not None
    doc_id = created.document.id
    deleted = life.delete(doc_id)
    assert deleted.outcome == LifecycleOutcome.DELETED
    assert deleted.document is not None
    assert deleted.document.status == DocumentStatus.DELETED
    assert store.count_for_doc(doc_id) == 0

    again = life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=prep)
    assert again.outcome == LifecycleOutcome.CREATED
    assert again.document is not None
    assert again.document.id != doc_id


def test_active_version_filter_rule(
    life: DocumentLifecycle,
    store: ChunkStore,
    db_session: Session,
) -> None:
    created = life.add(
        "a.txt",
        BASE_TEXT.encode(),
        external_key="k1",
        prepared=_prepare(BASE_TEXT),
    )
    assert created.document is not None
    doc = created.document
    updated_text = BASE_TEXT + " follow up patch applied to settlement gateway"
    life.update("k1", "a.txt", updated_text.encode(), prepared=_prepare(updated_text))
    db_session.refresh(doc)
    payloads = store.get_payloads(store.list_point_ids_for_doc(doc.id))
    active = [p for p in payloads.values() if p.get("version") == doc.active_version]
    stale = [p for p in payloads.values() if p.get("version") != doc.active_version]
    assert active
    assert stale == []


def test_simulated_crash_then_reconcile(
    db_session: Session,
    store: ChunkStore,
) -> None:
    life = DocumentLifecycle(
        db_session,
        store,
        stop_before_active=True,
    )
    prep = _prepare(BASE_TEXT)
    result = life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=prep)
    assert result.document is not None
    doc_id = result.document.id
    db_session.refresh(result.document)
    assert result.document.status == DocumentStatus.INDEXING
    assert result.document.active_version == 0
    assert store.count_for_doc(doc_id) >= 1

    report = reconcile_session(db_session, store)
    assert doc_id in report.activated
    doc = db_session.get(type(result.document), doc_id)
    assert doc is not None
    assert doc.status == DocumentStatus.ACTIVE
    assert doc.active_version == 1


def test_simulated_crash_after_version_switch(
    db_session: Session,
    store: ChunkStore,
) -> None:
    life = DocumentLifecycle(db_session, store)
    life.add("a.txt", BASE_TEXT.encode(), external_key="k1", prepared=_prepare(BASE_TEXT))
    crashing = DocumentLifecycle(
        db_session,
        store,
        stop_before_version_cleanup=True,
    )
    updated = BASE_TEXT + " new version with different chunk bodies for operators"
    result = crashing.update(
        "k1",
        "a.txt",
        updated.encode(),
        prepared=_prepare(updated),
    )
    assert result.document is not None
    doc_id = result.document.id
    db_session.refresh(result.document)
    # Crashed after setting new version while still INDEXING; old points may remain.
    assert result.document.active_version == 2
    assert result.document.status == DocumentStatus.INDEXING

    report = reconcile_session(db_session, store)
    assert doc_id in report.activated
    payloads = store.get_payloads(store.list_point_ids_for_doc(doc_id))
    assert payloads
    assert all(p.get("version") == 2 for p in payloads.values())


def test_pipeline_with_injected_fakes(life: DocumentLifecycle) -> None:
    data = BASE_TEXT.encode()
    result = life.add(
        "doc.txt",
        data,
        external_key="fake-key",
        parse_fn=_fake_parse,
        chunk_fn=_chunk_fn,
    )
    assert result.outcome == LifecycleOutcome.CREATED
    assert result.document is not None
    assert result.document.status == DocumentStatus.ACTIVE
