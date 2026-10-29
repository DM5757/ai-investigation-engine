.PHONY: install test lint typecheck bench docker-build docker-run migrate

install:
	uv sync --all-groups

test:
	uv run pytest -q

lint:
	uv run ruff check app tests scripts

typecheck:
	uv run mypy app

bench:
	uv run python scripts/bench_embeddings_rss.py

docker-build:
	docker build -t ai-investigation-engine:local .

docker-run:
	docker run --rm -p 8000:8000 -e DATABASE_URL=sqlite+pysqlite:////tmp/app.db ai-investigation-engine:local

migrate:
	uv run alembic upgrade head
