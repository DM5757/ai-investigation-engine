"""FastAPI dependency providers — the only wiring place."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_session_factory


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def db_session(settings: SettingsDep) -> Generator[Session, None, None]:
    factory = get_session_factory(settings.database_url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(db_session)]
