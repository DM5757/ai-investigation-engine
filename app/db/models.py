"""SQLAlchemy ORM models (Phase 1 baseline)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class HealthProbe(Base):
    """Tiny table used to verify Alembic + DB connectivity in Phase 1."""

    __tablename__ = "health_probes"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    note: Mapped[str] = mapped_column(Text, default="ok")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
