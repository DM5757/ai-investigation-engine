"""One-shot: mark stuck INDEXING docs as FAILED."""

from __future__ import annotations

from sqlalchemy import text

from app.config import get_settings
from app.db.session import get_engine


def main() -> None:
    settings = get_settings()
    eng = get_engine(settings.database_url)
    with eng.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE documents SET status = 'FAILED', "
                "error_message = 'interrupted bulk' WHERE status = 'INDEXING'"
            )
        )
        print(f"cleared_indexing={result.rowcount}")


if __name__ == "__main__":
    main()
