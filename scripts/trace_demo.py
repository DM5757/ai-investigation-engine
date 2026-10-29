"""Runnable investigation trace demo (skips live LLM if no keys)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.index.qdrant_store import ChunkPoint, InMemoryChunkStore
from app.investigation.engine import InvestigationEngine
from app.llm.gateway import build_gateway
from app.retrieval.bm25_sparse import Bm25Encoder
from app.retrieval.hybrid import HybridRetriever

CORPUS = {
    "demo_a": (
        "Incident report: PaymentService latency spiked after the March 12 deploy "
        "of auth-gateway."
    ),
    "demo_b": (
        "Change log: The March 12 auth-gateway release caused PaymentService timeouts."
    ),
}


def main() -> int:
    settings = get_settings()
    gateway = build_gateway(settings)
    store = InMemoryChunkStore(dense_size=32, embedding_short="demo")
    store.ensure_collection()
    bm25 = Bm25Encoder()

    class _HashEmbed:
        model_name = "demo-hash"
        dimensions = 32

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            out: list[list[float]] = []
            for text in texts:
                vec = [0.0] * 32
                for tok in text.lower().split():
                    h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
                    vec[h % 32] += 1.0
                n = sum(x * x for x in vec) ** 0.5
                out.append([x / n for x in vec] if n else vec)
            return out

        def embed_query(self, text: str) -> list[float]:
            return self.embed_documents([text])[0]

    embedder = _HashEmbed()
    points: list[ChunkPoint] = []
    for doc_id, text in CORPUS.items():
        sparse = bm25.encode_document(text)
        points.append(
            ChunkPoint(
                point_id=f"{doc_id}:0",
                doc_id=doc_id,
                version=1,
                chunk_index=0,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                text=text,
                dense_vector=embedder.embed_documents([text])[0],
                sparse_indices=list(sparse.indices),
                sparse_values=list(sparse.values),
                payload_extra={"title": doc_id},
            )
        )
    store.upsert_chunks(points)
    retriever = HybridRetriever(store, embedder, bm25, settings=settings)
    llm = gateway if gateway.available else None
    if llm is None:
        print("HUMAN ACTION REQUIRED: GROQ_API_KEY/GEMINI_API_KEY absent.")
        print("Running degraded demo (retrieval only, status=llm_unavailable).")
    engine = InvestigationEngine(retriever, store, llm=llm, settings=settings)
    result = engine.investigate(
        "What caused PaymentService disruptions after the auth-gateway deploy?"
    )
    summary = {
        "status": result.status,
        "answer": result.answer,
        "degraded": result.degraded,
        "trace_stages": [e.stage for e in result.trace],
        "usage_calls": result.usage.calls,
    }
    print(json.dumps(summary, indent=2))
    out = Path("docs/evidence/phase4_trace_demo.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
