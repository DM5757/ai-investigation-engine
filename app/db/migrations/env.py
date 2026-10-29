"""Alembic migration environment."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db.models import Base
from app.db.url import normalize_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    """Prefer process env, then Settings (.env), always Psycopg-3-normalized."""
    raw = os.getenv("DATABASE_URL")
    if not raw:
        get_settings.cache_clear()
        raw = get_settings().database_url
    return normalize_database_url(raw)


# ConfigParser treats % specially; escape for alembic.ini overlay.
_db_url = _resolve_database_url()
config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    url = normalize_database_url(
        (config.get_main_option("sqlalchemy.url") or "").replace("%%", "%")
    )
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {}) or {}
    # engine_from_config reads the escaped URL; SQLAlchemy accepts %%.
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
