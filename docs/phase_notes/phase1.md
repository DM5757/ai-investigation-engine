# Phase 1 notes (scaffold + local benchmarks)

## What was built

- `uv` project with `app/` package layout
- Settings (`app/config.py`), JSON logging, error hierarchy
- Health/ready/version endpoints
- SQLAlchemy + Alembic baseline (`health_probes`)
- Candidate FastEmbed provider (not loaded at app startup by default)
- Dockerfile, Makefile, GitHub Actions CI, `render.yaml`
- RSS/latency bench script: `scripts/bench_embeddings_rss.py`

## Key functions / modules

1. `app.main.create_app` — app factory
2. `app.config.get_settings` — validated env config
3. `app.api.routes_health.health` / `ready`
4. `app.deps.db_session` — DI wiring
5. `app.embeddings.fastembed_provider.FastEmbedProvider`
6. `scripts.bench_embeddings_rss.main` — resource gate for Render 512 MB

## Hosting revision

Render Free is primary. Northflank rejected (card required). Neon + Qdrant unchanged. Embedding strategy **not finalized** until bench evidence is reviewed.

## Interview questions to practice

1. Why is app disk treated as ephemeral on Render Free?
2. What does `/api/health` vs `/api/health/ready` guarantee?
3. Why is `EMBEDDING_ENABLED_AT_STARTUP` default false?
4. How will keep-alive interact with Render’s 15-minute sleep and 750 instance-hours?
5. What happens if peak RSS exceeds ~450 MB under a 512 MB budget?
