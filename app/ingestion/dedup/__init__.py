"""Exact and near-duplicate detection utilities."""

from app.ingestion.dedup.hashing import chunk_content_hash, content_hash
from app.ingestion.dedup.simhash import (
    band_values,
    compute_simhash,
    find_near_duplicates,
    hamming_distance,
)

__all__ = [
    "band_values",
    "chunk_content_hash",
    "compute_simhash",
    "content_hash",
    "find_near_duplicates",
    "hamming_distance",
]
