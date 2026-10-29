"""Unit tests for admin token dependency."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.api.security import require_admin_token
from app.config import Settings
from app.errors import Unauthorized


def _settings_with_token(token: str | None) -> Settings:
    settings = Settings.model_construct()  # type: ignore[call-arg]
    if token is None:
        object.__setattr__(settings, "admin_token", None)
    else:
        object.__setattr__(settings, "admin_token", SecretStr(token))
    return settings


def test_require_admin_missing_config() -> None:
    with pytest.raises(Unauthorized):
        require_admin_token(_settings_with_token(None), x_admin_token="anything")


def test_require_admin_wrong_token() -> None:
    with pytest.raises(Unauthorized):
        require_admin_token(_settings_with_token("secret"), x_admin_token="nope")


def test_require_admin_ok() -> None:
    require_admin_token(_settings_with_token("secret"), x_admin_token="secret")
