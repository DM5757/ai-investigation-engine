"""Database URL normalization for SQLAlchemy dialects."""

from __future__ import annotations


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy URL that uses Psycopg 3 for Postgres.

    Neon and many hosted providers emit ``postgresql://`` or ``postgres://``.
    SQLAlchemy maps bare ``postgresql://`` to the legacy ``psycopg2`` driver,
    which is *not* installed (we depend on ``psycopg`` v3). Rewrite to
    ``postgresql+psycopg://`` so production images resolve the correct package.
    SQLite and already-qualified dialects are left unchanged.
    """
    stripped = url.strip()
    if not stripped:
        return stripped

    lower = stripped.lower()
    if lower.startswith("sqlite"):
        return stripped
    if "+psycopg2://" in lower:
        # Explicit legacy driver → force Psycopg 3.
        idx = lower.index("+psycopg2://")
        return stripped[:idx] + "+psycopg://" + stripped[idx + len("+psycopg2://") :]
    if "+psycopg://" in lower:
        return stripped
    if lower.startswith("postgres://"):
        return "postgresql+psycopg://" + stripped[len("postgres://") :]
    if lower.startswith("postgresql://"):
        return "postgresql+psycopg://" + stripped[len("postgresql://") :]
    return stripped
