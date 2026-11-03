"""Feature-flag selection: experimental reader vs legacy finalize."""

from __future__ import annotations

from app.config import Settings


def test_experimental_passage_reader_defaults_off() -> None:
    settings = Settings(DATABASE_URL="sqlite+pysqlite:///:memory:")
    assert settings.experimental_passage_reader is False


def test_experimental_passage_reader_can_enable_via_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("EXPERIMENTAL_PASSAGE_READER", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    try:
        assert settings.experimental_passage_reader is True
    finally:
        get_settings.cache_clear()
