"""Live InvestigationEngine smoke (requires GROQ_API_KEY in .env or environment)."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.index.qdrant_store import ChunkPoint, QdrantChunkStore
from app.investigation.engine import InvestigationEngine
from app.llm.gateway import build_gateway
from app.retrieval.bm25_sparse import Bm25Encoder
from app.retrieval.hybrid import HybridRetriever

pytestmark = pytest.mark.live

CORPUS = {
    "live_a": (
        "Incident report: PaymentService latency spiked after the March 12 deploy "
        "of auth-gateway. Payment processing disruptions lasted six hours."
    ),
    "live_b": (
        "Change log: The March 12 auth-gateway release caused PaymentService "
        "timeouts in checkout across the payments region."
    ),
    "live_c": "InventoryService remained healthy throughout March.",
}


def _secret_set(value: object | None) -> bool:
    if value is None:
        return False
    get_secret = getattr(value, "get_secret_value", None)
    if callable(get_secret):
        return bool(str(get_secret()).strip())
    return bool(str(value).strip())


def _load_live_settings() -> Settings:
    """Reload settings from .env (pydantic-settings); do not print secrets."""
    get_settings.cache_clear()
    base = get_settings()
    if not _secret_set(base.groq_api_key):
        pytest.skip("GROQ_API_KEY absent in .env / environment — live LLM test skipped")
    return base.model_copy(
        update={
            "retrieval_top_k": 5,
            "max_tool_rounds": 4,
            "llm_budget_max_calls": 12,
            "llm_timeout_s": 60.0,
        }
    )


@pytest.fixture(scope="module")
def live_engine() -> InvestigationEngine:
    settings = _load_live_settings()
    try:
        from app.embeddings.fastembed_provider import FastEmbedProvider

        embedder = FastEmbedProvider(model_name=settings.embedding_model)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"FastEmbed unavailable for live test: {exc}")

    try:
        store = QdrantChunkStore.local(
            strategy="structure_aware",
            embedding_short="bge-small",
            dense_size=embedder.dimensions,
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"QdrantChunkStore.local failed: {exc}")

    store.ensure_collection()
    bm25 = Bm25Encoder()
    points: list[ChunkPoint] = []
    for doc_id, text in CORPUS.items():
        dense = embedder.embed_documents([text])[0]
        sparse = bm25.encode_document(text)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"live:{doc_id}:0"))
        points.append(
            ChunkPoint(
                point_id=point_id,
                doc_id=doc_id,
                version=1,
                chunk_index=0,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                text=text,
                dense_vector=dense,
                sparse_indices=list(sparse.indices),
                sparse_values=list(sparse.values),
                payload_extra={"title": doc_id},
            )
        )
    store.upsert_chunks(points)
    gateway = build_gateway(settings)
    if not gateway.available:
        pytest.skip("No LLM providers configured despite GROQ_API_KEY check")
    retriever = HybridRetriever(store, embedder, bm25, settings=settings)
    return InvestigationEngine(retriever, store, llm=gateway, settings=settings)


def test_live_multi_doc_investigation(live_engine: InvestigationEngine) -> None:
    result = live_engine.investigate(
        "What caused PaymentService disruptions in March, and which documents support this?"
    )
    assert result.status in ("answered", "partial", "conflicting")
    assert result.trace
    # Redacted trace (no secrets) for evidence
    evidence_dir = Path("docs/evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": result.status,
        "answer": result.answer,
        "citations": [c.model_dump() for c in result.citations],
        "claim_docs": sorted({c.doc_id for c in result.claims if c.verified}),
        "trace": [
            {
                "stage": e.stage,
                "inputs_summary": e.inputs_summary,
                "outputs_summary": e.outputs_summary,
                "latency_ms": e.latency_ms,
                "tokens": e.tokens.model_dump(),
            }
            for e in result.trace
        ],
        "usage": result.usage.model_dump(),
        "note": "Redacted live trace; API keys never stored.",
    }
    out = evidence_dir / "phase4_live_trace.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert out.exists()
