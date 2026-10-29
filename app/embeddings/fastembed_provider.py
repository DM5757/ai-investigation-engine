"""fastembed-backed dense embeddings (candidate provider; optional at startup)."""

from __future__ import annotations

import os

from fastembed import TextEmbedding

# BGE query instruction required by the model card for retrieval quality.
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class FastEmbedProvider:
    """ONNX embeddings via fastembed. Heavy — do not load blindly on 512 MB hosts."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self.model_name = model_name
        cache_dir = os.environ.get("FASTEMBED_CACHE_PATH")
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dimensions = 384

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for vec in self._model.embed(texts):
            vectors.append([float(x) for x in vec.tolist()])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        prefixed = text if text.startswith(_BGE_QUERY_PREFIX) else f"{_BGE_QUERY_PREFIX}{text}"
        vec = list(self._model.embed([prefixed]))[0]
        return [float(x) for x in vec.tolist()]
