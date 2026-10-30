"""Deploy-time build metadata (no secrets)."""

from __future__ import annotations

import os
import re

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def resolve_git_commit(*, configured: str | None = None) -> str:
    """Return the best-known git commit SHA for this process.

    Prefers explicit config / env injection from the host (Render sets
    ``RENDER_GIT_COMMIT``). Never reads ``.git`` at runtime (absent in Docker).
    """
    candidates = [
        configured,
        os.environ.get("GIT_COMMIT"),
        os.environ.get("RENDER_GIT_COMMIT"),
        os.environ.get("SOURCE_COMMIT"),
        os.environ.get("COMMIT_SHA"),
    ]
    for raw in candidates:
        if not raw:
            continue
        value = raw.strip()
        if value.lower() in {"", "unknown", "none", "null"}:
            continue
        # Allow full or short SHAs; strip dirty suffixes like ``abc1234-dirty``.
        sha = value.split("-", 1)[0].strip()
        if _SHA_RE.match(sha):
            return sha.lower()
        # Non-SHA deploy labels still useful for observability
        if 4 <= len(value) <= 64 and all(c.isalnum() or c in "._/" for c in value):
            return value
    return "unknown"
