"""Embedding provider protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface for dense text embeddings."""

    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages (no query instruction prefix)."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query (may apply model-specific prefixes)."""
