"""One-shot Phase 5 API/UI smoke for evidence checklist (TestClient, no live LLM)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Base
from app.db.session import get_engine, get_session_factory
from app.deps import reset_process_singletons
from app.embeddings.zero_provider import ZeroEmbeddingProvider
from app.index.qdrant_store import InMemoryChunkStore
from app.main import create_app


def main() -> None:
    td = tempfile.mkdtemp()
    db = Path(td) / "smoke.sqlite"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db.as_posix()}"
    os.environ["ADMIN_TOKEN"] = "checklist-admin"
    os.environ["EMBEDDING_ENABLED_AT_STARTUP"] = "false"
    os.environ.pop("GROQ_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("QDRANT_URL", None)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    reset_process_singletons()
    Base.metadata.create_all(get_engine(os.environ["DATABASE_URL"]))

    app = create_app()
    store = InMemoryChunkStore()
    store.ensure_collection()
    steps: list[str] = []
    with TestClient(app) as client:
        client.app.state.chunk_store = store  # type: ignore[attr-defined]
        client.app.state.embedder_override = ZeroEmbeddingProvider()  # type: ignore[attr-defined]
        client.app.state.llm_override = None  # type: ignore[attr-defined]

        r = client.get("/")
        steps.append(
            f"GET / -> {r.status_code}; has_brand={'AI Investigation Engine' in r.text}"
        )
        r = client.get("/static/app.js")
        steps.append(f"GET /static/app.js -> {r.status_code}; setText={'setText' in r.text}")
        r = client.get("/static/style.css")
        steps.append(f"GET /static/style.css -> {r.status_code}")
        r = client.get("/api/health")
        steps.append(f"GET /api/health -> {r.status_code} {r.json()}")
        r = client.get("/api/health/ready")
        body = r.json()
        steps.append(
            f"GET /api/health/ready -> {r.status_code} db={body.get('database')} "
            f"llm={body.get('llm_status')} qdrant={body.get('qdrant_status')}"
        )
        r = client.get("/api/version")
        steps.append(f"GET /api/version -> {r.status_code} {r.json()}")
        r = client.get("/api/stats")
        steps.append(f"GET /api/stats -> {r.status_code} keys={list(r.json().keys())}")
        r = client.get("/api/eval/runs")
        steps.append(
            f"GET /api/eval/runs -> {r.status_code} note={r.json().get('note', '')[:80]}"
        )
        r = client.post(
            "/api/documents",
            files={
                "file": (
                    "smoke.txt",
                    b"PaymentService failed in March after deploy.",
                    "text/plain",
                )
            },
            headers={"X-Admin-Token": "checklist-admin"},
        )
        doc = r.json()
        steps.append(
            f"POST /api/documents (admin) -> {r.status_code} "
            f"outcome={doc.get('outcome')} id={doc.get('document_id')}"
        )
        doc_id = doc.get("document_id")
        r = client.get("/api/documents")
        steps.append(f"GET /api/documents -> {r.status_code} total={r.json().get('total')}")
        r = client.get(f"/api/documents/{doc_id}/chunks")
        steps.append(
            f"GET chunks -> {r.status_code} n={len(r.json().get('items', []))}"
        )
        r = client.post(
            "/api/query",
            json={
                "question": "What happened to PaymentService in March?",
                "mode": "sparse",
            },
        )
        q = r.json()
        steps.append(
            f"POST /api/query -> {r.status_code} status={q.get('status')} "
            f"sources={len(q.get('sources', []))} "
            f"missing={bool(q.get('missing_information'))}"
        )
        r = client.get("/api/metrics")
        steps.append(f"GET /api/metrics -> {r.status_code} {r.json()}")
        r = client.get("/api/health")
        steps.append(
            "headers "
            f"nosniff={r.headers.get('x-content-type-options')} "
            f"frame={r.headers.get('x-frame-options')} "
            f"cors={r.headers.get('access-control-allow-origin')}"
        )
        r = client.post(
            "/api/documents",
            files={"file": ("x.txt", b"hi", "text/plain")},
        )
        steps.append(f"POST docs no token -> {r.status_code}")

    print("\n".join(steps))


if __name__ == "__main__":
    main()
