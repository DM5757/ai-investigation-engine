"""Postgres dialect URL normalization (Psycopg 3)."""

from __future__ import annotations

import pytest

from app.db.url import normalize_database_url


@pytest.mark.parametrize(
    ("raw", "expected_prefix"),
    [
        ("postgresql://user:pass@host/db", "postgresql+psycopg://"),
        ("postgres://user:pass@host/db", "postgresql+psycopg://"),
        ("postgresql+psycopg://user:pass@host/db", "postgresql+psycopg://"),
        ("postgresql+psycopg2://user:pass@host/db", "postgresql+psycopg://"),
        ("sqlite+pysqlite:///:memory:", "sqlite+pysqlite://"),
        ("sqlite:///./local.db", "sqlite:///"),
    ],
)
def test_normalize_database_url_prefixes(raw: str, expected_prefix: str) -> None:
    out = normalize_database_url(raw)
    assert out.startswith(expected_prefix)
    assert "psycopg2" not in out.lower() or out.lower().startswith("sqlite")


def test_normalize_preserves_query_and_credentials_shape() -> None:
    raw = "postgresql://u:p@ep-x.neon.tech/neondb?sslmode=require"
    out = normalize_database_url(raw)
    assert out == "postgresql+psycopg://u:p@ep-x.neon.tech/neondb?sslmode=require"


def test_settings_normalizes_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings, get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    get_settings.cache_clear()
    settings = Settings()
    assert settings.database_url.startswith("postgresql+psycopg://")
    get_settings.cache_clear()
