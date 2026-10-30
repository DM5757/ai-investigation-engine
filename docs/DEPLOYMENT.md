# Deployment

## Architecture

- **App host:** Render Free (Docker), sleeps after ~15 minutes idle (~1 minute cold start)
- **Public URL:** https://ai-investigation-engine-scyz.onrender.com
- **State:** Neon Postgres + Qdrant Cloud (container disk is ephemeral)
- **Image:** multi-stage Dockerfile, non-root user, BGE-small ONNX cache baked
- **Deploy SHA:** `GET /api/version` → `git_commit` (must match intended `main` commit after deploy)

## Free-tier limits

| Resource | Limit |
| --- | --- |
| Render Free | 512 MB RAM, 0.1 CPU, 15 min sleep, 750 instance-hours/month |
| Measured peak (embeddings on) | **284.6 MiB** under Docker 512m hard limit (`docs/evidence/container_512m_bench.json`) |

## Environment variables

| Name | Required | Notes |
| --- | --- | --- |
| `DATABASE_URL` | yes | Neon for persistence; SQLite only for throwaway tests. Bare `postgresql://` is rewritten to `postgresql+psycopg://` (Psycopg 3). |
| `QDRANT_URL` / `QDRANT_API_KEY` | yes (prod) | Cloud cluster; local tests may use in-memory store |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | yes (prod answers) | Groq primary, Gemini fallback |
| `ADMIN_TOKEN` | yes (mutating APIs) | `X-Admin-Token` for document CRUD |
| `EMBEDDING_ENABLED_AT_STARTUP` | no | Prefer `false` on Render Free; model lazy-loads on first query |
| `ENABLE_BENCH_ENDPOINTS` | no | Keep `false` on public URL |
| `FASTEMBED_CACHE_PATH` | no | Default `/app/model_cache` in image |
| `INVESTIGATION_WALL_CLOCK_S` | no | Default 300s (Render Free latency) |

Full list: `.env.example`.

## Persistence and rebuild

Postgres is the source of truth for documents/versions/chunks. Qdrant is a derived index rebuildable via ingest/reconcile scripts (`scripts/bulk_ingest.py`, `scripts/reconcile.py`, `scripts/verify_counts.py`). Do not rely on Render disk for corpus state.

## Rollback

Redeploy a previous Render deploy from the dashboard, or `git revert` + push to `main`. Do not force-push over submission tags.

## Verification checklist after deploy

1. `GET /api/version` — `git_commit` matches intended SHA
2. `GET /api/health` and `GET /api/health/ready`
3. `GET /api/stats` — ACTIVE document count matches Neon measurement
4. One bounded `POST /api/query` smoke (respect free-tier LLM quotas)
