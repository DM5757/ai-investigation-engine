.PHONY: install test lint typecheck bench docker-build docker-run migrate

install:
	uv sync --all-groups

# Prefer `python -m` so Windows Smart App Control does not block unsigned venv shims
# (mypy.exe / pytest.exe). See docs/evidence/windows_security_tools.txt.
test:
	uv run python -m pytest -q

lint:
	uv run ruff check app tests scripts

typecheck:
	uv run python -m mypy app

bench:
	uv run python scripts/bench_embeddings_rss.py

docker-build:
	docker build -t ai-investigation-engine:local .

docker-run:
	docker run --rm -p 8000:8000 -e DATABASE_URL=sqlite+pysqlite:////tmp/app.db ai-investigation-engine:local

migrate:
	uv run alembic upgrade head
