"""Health endpoint unit tests."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_version() -> None:
    client = TestClient(create_app())
    response = client.get("/api/version")
    assert response.status_code == 200
    assert "version" in response.json()


def test_bench_embed_disabled_by_default() -> None:
    client = TestClient(create_app())
    response = client.post("/api/bench/embed")
    assert response.status_code == 404


def test_ready_with_sqlite(monkeypatch: object) -> None:
    import os

    os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
    from app.config import get_settings

    get_settings.cache_clear()
    from app.db.models import Base
    from app.db.session import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    client = TestClient(create_app())
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
