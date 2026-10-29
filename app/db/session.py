"""Engine and session factory."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.url import normalize_database_url


@lru_cache
def get_engine(database_url: str) -> Engine:
    url = normalize_database_url(database_url)
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    url = normalize_database_url(database_url)
    return sessionmaker(
        bind=get_engine(url),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
