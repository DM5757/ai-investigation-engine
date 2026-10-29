"""Admin token authentication for mutating document endpoints."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header

from app.deps import SettingsDep
from app.errors import Unauthorized


def require_admin_token(
    settings: SettingsDep,
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> None:
    """Reject mutating requests unless X-Admin-Token matches (constant-time)."""
    expected = settings.admin_token
    if expected is None:
        raise Unauthorized("ADMIN_TOKEN is not configured")
    provided = x_admin_token or ""
    secret = expected.get_secret_value()
    if not secret or not secrets.compare_digest(provided, secret):
        raise Unauthorized("invalid or missing X-Admin-Token")


AdminAuth = Annotated[None, Depends(require_admin_token)]
