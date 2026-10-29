"""Content hashing helpers for exact-duplicate detection."""

from __future__ import annotations

import hashlib


def content_hash(text: str) -> str:
    """SHA-256 hex digest of UTF-8 text (normalized content fingerprint)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_content_hash(text: str) -> str:
    """Hash a single chunk body (same algorithm as document content hash)."""
    return content_hash(text)
