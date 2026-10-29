"""FastAPI dependency providers — the only wiring place."""

from __future__ import annotations

import logging
from collections.abc import Generator, Sequence
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_session_factory
from app.embeddings.provider import EmbeddingProvider
from app.embeddings.zero_provider import ZeroEmbeddingProvider
from app.index.qdrant_store import (
    ChunkStore,
    InMemoryChunkStore,
    QdrantChunkStore,
    make_local_chunk_store,
)
from app.ingestion.lifecycle import DocumentLifecycle
from app.investigation.engine import InvestigationEngine
from app.llm.gateway import build_gateway
from app.llm.types import LLMClient
from app.retrieval.bm25_sparse import Bm25Encoder
from app.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)

# Process-scoped singletons (lazy).
_chunk_store: ChunkStore | None = None
_embedder: EmbeddingProvider | None = None
_bm25: Bm25Encoder | None = None
_llm_sentinel = object()
_llm: LLMClient | None | object = _llm_sentinel


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def db_session(settings: SettingsDep) -> Generator[Session, None, None]:
    factory = get_session_factory(settings.database_url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(db_session)]


def get_or_create_chunk_store(settings: Settings) -> ChunkStore:
    """Qdrant remote if URL set, else local/memory via make_local_chunk_store."""
    global _chunk_store
    if _chunk_store is not None:
        return _chunk_store
    strategy = settings.chunk_strategy
    short = settings.embedding_model_short
    dense = settings.dense_vector_size
    if settings.qdrant_url:
        key = (
            settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        )
        try:
            store: ChunkStore = QdrantChunkStore.remote(
                settings.qdrant_url,
                api_key=key,
                strategy=strategy,
                embedding_short=short,
                dense_size=dense,
            )
            store.ensure_collection()
            _chunk_store = store
            return store
        except Exception:  # noqa: BLE001
            logger.exception("remote Qdrant unavailable; falling back to local store")
    _chunk_store = make_local_chunk_store(
        path=settings.qdrant_path,
        strategy=strategy,
        embedding_short=short,
        dense_size=dense,
    )
    _chunk_store.ensure_collection()
    return _chunk_store


def get_or_create_embedder(
    settings: Settings,
    *,
    app_state: Any | None = None,
) -> EmbeddingProvider:
    """Prefer FastEmbed when enabled/cached on app.state; else zero vectors."""
    global _embedder
    if _embedder is not None:
        return _embedder
    if app_state is not None:
        loaded = getattr(app_state, "embedding_provider", None)
        if loaded is not None and isinstance(loaded, EmbeddingProvider):
            _embedder = loaded
            return loaded
    if settings.embedding_enabled_at_startup:
        try:
            from app.embeddings.fastembed_provider import FastEmbedProvider

            provider: EmbeddingProvider = FastEmbedProvider(model_name=settings.embedding_model)
            _embedder = provider
            return provider
        except Exception:  # noqa: BLE001
            logger.exception("FastEmbed load failed; using ZeroEmbeddingProvider")
    zero = ZeroEmbeddingProvider(dimensions=settings.dense_vector_size)
    _embedder = zero
    return zero


def get_or_create_bm25(settings: Settings) -> Bm25Encoder:
    global _bm25
    if _bm25 is not None:
        return _bm25
    _bm25 = Bm25Encoder(
        k1=settings.bm25_k1,
        b=settings.bm25_b,
        avgdl=settings.bm25_avgdl,
    )
    return _bm25


def get_or_create_llm(settings: Settings) -> LLMClient | None:
    """Build gateway once; empty providers → None (degraded engine)."""
    global _llm
    if _llm is not _llm_sentinel:
        return _llm  # type: ignore[return-value]
    gateway = build_gateway(settings)
    if not gateway.providers:
        _llm = None
        return None
    _llm = gateway
    return gateway


def reset_process_singletons() -> None:
    """Test helper: clear process-scoped wiring."""
    global _chunk_store, _embedder, _bm25, _llm
    _chunk_store = None
    _embedder = None
    _bm25 = None
    _llm = _llm_sentinel


def chunk_store_dep(request: Request, settings: SettingsDep) -> ChunkStore:
    override = getattr(request.app.state, "chunk_store", None)
    if override is not None:
        return override  # type: ignore[no-any-return]
    return get_or_create_chunk_store(settings)


ChunkStoreDep = Annotated[ChunkStore, Depends(chunk_store_dep)]


def embedder_dep(request: Request, settings: SettingsDep) -> EmbeddingProvider:
    override = getattr(request.app.state, "embedder_override", None)
    if override is not None:
        return override  # type: ignore[no-any-return]
    return get_or_create_embedder(settings, app_state=request.app.state)


EmbedderDep = Annotated[EmbeddingProvider, Depends(embedder_dep)]


def bm25_dep(settings: SettingsDep) -> Bm25Encoder:
    return get_or_create_bm25(settings)


Bm25Dep = Annotated[Bm25Encoder, Depends(bm25_dep)]


def hybrid_retriever_dep(
    store: ChunkStoreDep,
    embedder: EmbedderDep,
    bm25: Bm25Dep,
    settings: SettingsDep,
) -> HybridRetriever:
    return HybridRetriever(store=store, embedder=embedder, bm25=bm25, settings=settings)


HybridRetrieverDep = Annotated[HybridRetriever, Depends(hybrid_retriever_dep)]


def document_lifecycle_dep(
    session: DbSession,
    store: ChunkStoreDep,
    embedder: EmbedderDep,
    bm25: Bm25Dep,
    settings: SettingsDep,
) -> DocumentLifecycle:
    def _embed(texts: Sequence[str]) -> list[list[float]]:
        return embedder.embed_documents(list(texts))

    return DocumentLifecycle(
        session,
        store,
        chunk_strategy=settings.chunk_strategy,
        simhash_threshold=settings.simhash_threshold,
        near_duplicate_policy=settings.near_duplicate_policy,
        embed_fn=_embed,
        sparse_encoder=bm25,
        dense_dims=settings.dense_vector_size,
    )


DocumentLifecycleDep = Annotated[DocumentLifecycle, Depends(document_lifecycle_dep)]


def investigation_engine_dep(
    request: Request,
    retriever: HybridRetrieverDep,
    store: ChunkStoreDep,
    settings: SettingsDep,
) -> InvestigationEngine:
    if hasattr(request.app.state, "llm_override"):
        llm: LLMClient | None = request.app.state.llm_override
    else:
        llm = get_or_create_llm(settings)
    engine = InvestigationEngine(
        retriever=retriever,
        store=store,
        llm=llm,
        settings=settings,
    )
    # Optional per-request retrieval mode override set by query route.
    mode = getattr(request.state, "retrieval_mode", None)
    if mode is not None:
        request.state.investigation_engine = engine
    return engine


InvestigationEngineDep = Annotated[InvestigationEngine, Depends(investigation_engine_dep)]


__all__ = [
    "Bm25Dep",
    "ChunkStoreDep",
    "DbSession",
    "DocumentLifecycleDep",
    "EmbedderDep",
    "HybridRetrieverDep",
    "InMemoryChunkStore",
    "InvestigationEngineDep",
    "SettingsDep",
    "chunk_store_dep",
    "db_session",
    "get_or_create_bm25",
    "get_or_create_chunk_store",
    "get_or_create_embedder",
    "get_or_create_llm",
    "reset_process_singletons",
    "settings_dep",
]
