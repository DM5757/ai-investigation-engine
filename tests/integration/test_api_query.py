"""Integration tests for /api/query (degraded / scripted, no live Groq)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.llm.scripted import ScriptedLLM, ScriptedResponse
from app.schemas.evidence import UsageStats
from tests.integration.api_helpers import ADMIN_HEADERS, sample_txt


def test_query_validation_empty(client: TestClient) -> None:
    res = client.post("/api/query", json={"question": ""})
    assert res.status_code == 422


def test_query_invalid_mode(client: TestClient) -> None:
    res = client.post("/api/query", json={"question": "What failed?", "mode": "magic"})
    assert res.status_code == 422


def test_query_degraded_llm_none(client: TestClient) -> None:
    name, data = sample_txt(
        "a.txt",
        "PaymentService outage in March was caused by a bad deploy.",
    )
    up = client.post(
        "/api/documents",
        files={"file": (name, data, "text/plain")},
        headers=ADMIN_HEADERS,
    )
    assert up.status_code == 200

    res = client.post(
        "/api/query",
        json={"question": "What caused the PaymentService outage?", "mode": "sparse"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "llm_unavailable"
    assert body["degraded"] is True
    assert "sources" in body
    assert body.get("mode") == "sparse"
    assert "missing_information" in body


def test_query_scripted_path(client: TestClient) -> None:
    name, data = sample_txt(
        "b.txt",
        "AuthService timeout in March followed the PaymentService deploy.",
    )
    assert (
        client.post(
            "/api/documents",
            files={"file": (name, data, "text/plain")},
            headers=ADMIN_HEADERS,
        ).status_code
        == 200
    )

    # Minimal scripted plan + empty tool loop → degraded-ish synthesize without tools.
    # Engine with ScriptedLLM that fails open on unexpected calls still needs careful queue;
    # for API smoke we only assert the endpoint accepts scripted override and returns JSON.
    client.app.state.llm_override = ScriptedLLM(  # type: ignore[attr-defined]
        [
            ScriptedResponse(
                content='{"question_type":"factual","sub_questions":'
                '[{"id":"q1","text":"What happened?","depends_on":[]}],'
                '"expected_answer_shape":"short_paragraph"}',
                usage=UsageStats(calls=1, total_tokens=10),
            ),
            # tool loop — no tool calls → finalize with empty retrieval claims
            ScriptedResponse(
                content="I need more evidence.",
                tool_calls=[],
                usage=UsageStats(calls=1, total_tokens=5),
            ),
        ]
    )

    res = client.post(
        "/api/query",
        json={"question": "What happened to AuthService in March?"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] in (
        "answered",
        "partial",
        "conflicting",
        "insufficient",
        "llm_unavailable",
    )
    assert isinstance(body.get("sources"), list)
    assert body.get("mode") == "hybrid_rerank"


def test_query_rate_limit_optional(tmp_path: object, monkeypatch: object) -> None:
    """Tight burst: second request can 429 when burst=1."""
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient as TC

    from app.config import get_settings
    from app.db.models import Base
    from app.db.session import get_engine, get_session_factory
    from app.deps import reset_process_singletons
    from app.embeddings.zero_provider import ZeroEmbeddingProvider
    from app.index.qdrant_store import InMemoryChunkStore
    from app.main import create_app

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    url = f"sqlite+pysqlite:///{(tmp_path / 'rl.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("QUERY_RATE_PER_MIN", "1")
    monkeypatch.setenv("QUERY_BURST", "1")
    monkeypatch.setenv("EMBEDDING_ENABLED_AT_STARTUP", "false")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    reset_process_singletons()
    Base.metadata.create_all(get_engine(url))

    app = create_app()
    store = InMemoryChunkStore()
    store.ensure_collection()
    with TC(app) as tc:
        tc.app.state.chunk_store = store  # type: ignore[attr-defined]
        tc.app.state.embedder_override = ZeroEmbeddingProvider()  # type: ignore[attr-defined]
        tc.app.state.llm_override = None  # type: ignore[attr-defined]
        r1 = tc.post("/api/query", json={"question": "first?"})
        r2 = tc.post("/api/query", json={"question": "second?"})
        assert r1.status_code == 200
        assert r2.status_code == 429
        assert r2.json()["error"]["code"] == "rate_limited"
