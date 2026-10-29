"""CLI entrypoint for index/DB reconcile.

Usage:
  uv run python scripts/reconcile.py
"""

from __future__ import annotations

import argparse
import logging

from app.config import get_settings
from app.db.models import Base
from app.db.session import get_engine, get_session_factory
from app.index.qdrant_store import ChunkStore, QdrantChunkStore, make_local_chunk_store
from app.ingestion.reconcile import ReconcileReport, reconcile_session


def build_store_from_settings() -> ChunkStore:
    settings = get_settings()
    if settings.qdrant_url:
        api_key = (
            settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        )
        return QdrantChunkStore.remote(
            settings.qdrant_url,
            api_key=api_key,
            strategy=settings.chunk_strategy,
            embedding_short=settings.embedding_model_short,
            dense_size=settings.dense_vector_size,
        )
    return make_local_chunk_store(
        path=settings.qdrant_path,
        strategy=settings.chunk_strategy,
        embedding_short=settings.embedding_model_short,
        dense_size=settings.dense_vector_size,
    )


def reconcile_all() -> ReconcileReport:
    settings = get_settings()
    engine = get_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = get_session_factory(settings.database_url)
    store = build_store_from_settings()
    session = factory()
    try:
        return reconcile_session(session, store)
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile DB document state with Qdrant")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    report = reconcile_all()
    print(
        "reconcile done:"
        f" activated={len(report.activated)}"
        f" cleaned={len(report.cleaned_versions)}"
        f" deletes={len(report.finished_deletes)}"
        f" failed={len(report.failed)}"
    )
    for note in report.notes:
        print(f"  note: {note}")


if __name__ == "__main__":
    main()
