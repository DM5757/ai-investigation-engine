"""Readiness returns sanitized 503 when the database dependency fails."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_ready_returns_503_when_database_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import db as db_pkg

    def boom(_url: str) -> Any:
        raise ModuleNotFoundError("No module named 'psycopg2'")

    monkeypatch.setattr("app.api.routes_health.get_session_factory", boom)
    # Also clear engine caches if any leftover.
    from app.db.session import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()

    client = TestClient(create_app())
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "unavailable"
    assert body["error"]["code"] == "database_unavailable"
    # Sanitized: do not echo driver ModuleNotFoundError text to clients.
    dumped = response.text.lower()
    assert "psycopg2" not in dumped
    assert "traceback" not in dumped
    _ = db_pkg


def test_ready_ok_with_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
    from app.config import get_settings
    from app.db.models import Base
    from app.db.session import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    client = TestClient(create_app())
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["database"] == "ok"
