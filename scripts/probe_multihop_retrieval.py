"""Probe retrieval modes for a multi-hop question against live Qdrant."""

from __future__ import annotations

import argparse
import json
import time

from app.config import get_settings
from app.embeddings.fastembed_provider import FastEmbedProvider
from app.index.qdrant_store import QdrantChunkStore
from app.retrieval.bm25_sparse import Bm25Encoder
from app.retrieval.hybrid import HybridRetriever


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--question",
        default=(
            "Is Ohio State University or California State University, "
            "Dominguez Hills further west?"
        ),
    )
    parser.add_argument(
        "--gold",
        default="Ohio State University|California State University, Dominguez Hills",
    )
    args = parser.parse_args()
    gold = {g.strip() for g in args.gold.split("|") if g.strip()}
    settings = get_settings()
    api_key = (
        settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    )
    assert settings.qdrant_url, "QDRANT_URL required"
    store = QdrantChunkStore.remote(
        settings.qdrant_url,
        api_key=api_key,
        strategy=settings.chunk_strategy,
        embedding_short=settings.embedding_model_short,
        dense_size=settings.dense_vector_size,
    )
    emb = FastEmbedProvider(settings.embedding_model)
    bm25 = Bm25Encoder(k1=settings.bm25_k1, b=settings.bm25_b, avgdl=settings.bm25_avgdl)
    retriever = HybridRetriever(store, emb, bm25, settings=settings)

    report: dict[str, object] = {"question": args.question, "gold": sorted(gold), "modes": {}}
    for mode in ("hybrid_rrf", "hybrid_rerank", "dense", "sparse"):
        t0 = time.perf_counter()
        hits = retriever.retrieve(args.question, k=8, mode=mode)  # type: ignore[arg-type]
        ms = (time.perf_counter() - t0) * 1000.0
        titles = [h.chunk.title for h in hits]
        covered = sorted({t for t in titles if t in gold})
        report["modes"][mode] = {  # type: ignore[index]
            "ms": round(ms, 1),
            "timings": dict(retriever.last_timings),
            "gold_in_top8": covered,
            "all_gold": set(covered) == gold,
            "top": [
                {
                    "title": h.chunk.title,
                    "score": round(float(h.fused_score or h.chunk.score), 4),
                    "doc_id": h.chunk.doc_id,
                }
                for h in hits[:8]
            ],
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
