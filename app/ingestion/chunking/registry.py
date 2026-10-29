"""Chunker registry."""

from __future__ import annotations

from app.ingestion.chunking.base import Chunker
from app.ingestion.chunking.fixed_window import FixedWindowChunker
from app.ingestion.chunking.structure_aware import StructureAwareChunker

_CHUNKERS: dict[str, Chunker] = {
    "fixed_window": FixedWindowChunker(),
    "structure_aware": StructureAwareChunker(),
}


def get_chunker(name: str) -> Chunker:
    """Return a registered chunker by strategy name."""
    try:
        return _CHUNKERS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_CHUNKERS))
        raise ValueError(f"Unknown chunker {name!r}; known: {known}") from exc


def list_chunkers() -> list[str]:
    """Return registered chunker names."""
    return sorted(_CHUNKERS)
