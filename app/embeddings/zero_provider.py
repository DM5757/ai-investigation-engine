"""Deterministic zero-vector embedder for degraded local tests."""

from __future__ import annotations


class ZeroEmbeddingProvider:
    """Returns zero vectors — retrieval relies on sparse/BM25 when dense is useless."""

    def __init__(self, *, dimensions: int = 384, model_name: str = "zero") -> None:
        self.dimensions = dimensions
        self.model_name = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimensions for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        _ = text
        return [0.0] * self.dimensions
