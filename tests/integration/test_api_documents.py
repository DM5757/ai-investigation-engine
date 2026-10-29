"""Integration tests for document API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Base
from app.db.session import get_engine, get_session_factory
from app.deps import reset_process_singletons
from app.embeddings.zero_provider import ZeroEmbeddingProvider
from app.index.qdrant_store import InMemoryChunkStore
from app.main import create_app
from tests.integration.api_helpers import ADMIN_HEADERS, sample_txt


def test_upload_requires_admin(client: TestClient) -> None:
    name, data = sample_txt()
    res = client.post(
        "/api/documents",
        files={"file": (name, data, "text/plain")},
    )
    assert res.status_code == 401


def test_upload_list_get_chunks_update_delete(client: TestClient) -> None:
    name, data = sample_txt("march.txt", "March outage affected PaymentService.")
    up = client.post(
        "/api/documents",
        files={"file": (name, data, "text/plain")},
        data={"external_key": "doc-march"},
        headers=ADMIN_HEADERS,
    )
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["outcome"] in ("created", "near_duplicate")
    doc_id = body["document_id"]
    assert doc_id

    listed = client.get("/api/documents")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    got = client.get(f"/api/documents/{doc_id}")
    assert got.status_code == 200
    assert got.json()["id"] == doc_id

    chunks = client.get(f"/api/documents/{doc_id}/chunks")
    assert chunks.status_code == 200
    assert len(chunks.json()["items"]) >= 1

    new_data = b"March outage affected PaymentService and AuthService."
    upd = client.put(
        f"/api/documents/{doc_id}",
        files={"file": ("march.txt", new_data, "text/plain")},
        headers=ADMIN_HEADERS,
    )
    assert upd.status_code == 200
    assert upd.json()["outcome"] in ("updated", "unchanged")

    re = client.post(f"/api/documents/{doc_id}/reindex", headers=ADMIN_HEADERS)
    assert re.status_code == 200

    deleted = client.delete(f"/api/documents/{doc_id}", headers=ADMIN_HEADERS)
    assert deleted.status_code == 200
    assert deleted.json()["outcome"] == "deleted"

    missing = client.get(f"/api/documents/{doc_id}")
    assert missing.status_code == 404


def test_upload_size_reject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "size.sqlite"
    url = f"sqlite+pysqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("UPLOAD_MAX_BYTES", "32")
    monkeypatch.setenv("EMBEDDING_ENABLED_AT_STARTUP", "false")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    reset_process_singletons()
    Base.metadata.create_all(get_engine(url))

    app = create_app()
    store = InMemoryChunkStore()
    store.ensure_collection()
    with TestClient(app) as tc:
        tc.app.state.chunk_store = store  # type: ignore[attr-defined]
        tc.app.state.embedder_override = ZeroEmbeddingProvider()  # type: ignore[attr-defined]
        big = b"x" * 100
        res = tc.post(
            "/api/documents",
            files={"file": ("big.txt", big, "text/plain")},
            headers=ADMIN_HEADERS,
        )
        assert res.status_code == 413
        assert res.json()["error"]["code"] == "payload_too_large"


def test_upload_bad_extension(client: TestClient) -> None:
    res = client.post(
        "/api/documents",
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "unsupported_format"
