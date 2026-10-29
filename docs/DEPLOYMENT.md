# Deployment (Phase 1)

## Architecture

- **App host:** Render Free (Docker), sleeps after 15 minutes idle
- **Public URL:** https://ai-investigation-engine-scyz.onrender.com
- **State:** Neon Postgres + Qdrant Cloud (not container disk)
- **Image:** multi-stage Dockerfile, non-root user, BGE-small ONNX cache baked

## Free-tier limits (28 Oct 2026)

| Resource | Limit |
| --- | --- |
| Render Free | 512 MB RAM, 0.1 CPU, 15 min sleep, 750 instance-hours/month |
| Measured peak (embeddings on) | **284.6 MiB** under Docker 512m hard limit |

## Environment variables

| Name | Required for skeleton | Notes |
| --- | --- | --- |
| `DATABASE_URL` | yes | Neon for persistence; SQLite only for throwaway tests. Bare `postgresql://` is rewritten to `postgresql+psycopg://` (Psycopg 3). Do not install/use psycopg2. |
| `EMBEDDING_ENABLED_AT_STARTUP` | no | `false` for walking skeleton; `true` OK per 512m bench |
| `ENABLE_BENCH_ENDPOINTS` | no | keep `false` on public URL |
| `FASTEMBED_CACHE_PATH` | no | default `/app/model_cache` in image |
| `QDRANT_URL` / `QDRANT_API_KEY` | later | Phase 2+ |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | later | Phase 4+ |
| `ADMIN_TOKEN` | later | mutating APIs |

## Rollback

Redeploy previous Render deploy from dashboard, or `git revert` + push.

## Rebuild index from Postgres

Not applicable until Phase 3 indexing exists. Protocol: Postgres is source of truth; Qdrant is derived and rebuildable via ingest/reconcile scripts.
