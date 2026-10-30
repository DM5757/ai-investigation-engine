"""Deploy git commit resolution."""

from __future__ import annotations

import os

from app.build_info import resolve_git_commit


def test_resolve_prefers_render_git_commit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef1234567890abcdef1234567890abcdef12")
    assert resolve_git_commit() == "abcdef1234567890abcdef1234567890abcdef12"


def test_resolve_configured_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RENDER_GIT_COMMIT", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert (
        resolve_git_commit(configured="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )


def test_resolve_unknown_when_absent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for key in ("GIT_COMMIT", "RENDER_GIT_COMMIT", "SOURCE_COMMIT", "COMMIT_SHA"):
        monkeypatch.delenv(key, raising=False)
    assert resolve_git_commit() == "unknown"
    assert "GIT_COMMIT" not in os.environ
