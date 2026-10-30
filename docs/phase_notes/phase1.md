# Phase 1 notes — scaffold, benchmarks, walking-skeleton deploy

## What was built

- `uv` project with `app/` package layout
- Settings (`app/config.py`), JSON logging, error hierarchy
- Health/ready/version endpoints
- SQLAlchemy + Alembic baseline (`health_probes`)
- FastEmbed provider (not loaded at app startup by default)
- Dockerfile, Makefile, GitHub Actions CI, `render.yaml`
- RSS/latency bench script: `scripts/bench_embeddings_rss.py`
- Public deploy on Render Free

## Key modules

1. `app.main.create_app` — app factory
2. `app.config.get_settings` — validated env config
3. `app.api.routes_health.health` / `ready`
4. `app.deps.db_session` — DI wiring
5. `app.embeddings.fastembed_provider.FastEmbedProvider`
6. `scripts.bench_embeddings_rss.main` — resource gate for Render 512 MB

## Verified evidence

- Local: `docs/evidence/phase1.txt`, `docs/evidence/container_512m_bench.json` (peak 284.6 MiB)
- Deploy: `docs/evidence/phase1_deploy.txt`
- Public URL: https://ai-investigation-engine-scyz.onrender.com

## Design notes

- Render Free disk is ephemeral; durable state belongs in Neon + Qdrant.
- `/api/health` is liveness; `/api/health/ready` checks dependency wiring.
- `EMBEDDING_ENABLED_AT_STARTUP=false` avoids loading ONNX during cold boot; first query pays lazy-load cost.
- Keep-alive mitigates sleep but consumes Free instance-hours.
