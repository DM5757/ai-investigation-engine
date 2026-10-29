"""Shared TestClient fixtures for Phase 5 API integration tests."""

from __future__ import annotations

from collections.abc import Iterator
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


@pytest.fixture()
def api_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db_path = tmp_path / "phase5.sqlite"
    url = f"sqlite+pysqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("EMBEDDING_ENABLED_AT_STARTUP", "false")
    monkeypatch.setenv("QUERY_RATE_PER_MIN", "120")
    monkeypatch.setenv("QUERY_BURST", "30")
    monkeypatch.setenv("LLM_DAILY_CAP", "0")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    reset_process_singletons()
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    yield tmp_path
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    reset_process_singletons()


@pytest.fixture()
def client(api_env: Path) -> Iterator[TestClient]:
    _ = api_env
    app = create_app()
    store = InMemoryChunkStore(strategy="structure_aware", embedding_short="bge-small")
    store.ensure_collection()
    with TestClient(app) as tc:
        tc.app.state.chunk_store = store  # type: ignore[attr-defined]
        tc.app.state.embedder_override = ZeroEmbeddingProvider()  # type: ignore[attr-defined]
        tc.app.state.llm_override = None  # type: ignore[attr-defined]
        yield tc


ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token"}


def sample_txt(
    name: str = "note.txt",
    body: str = "PaymentService failed in March.",
) -> tuple[str, bytes]:
    return name, body.encode("utf-8")
