# AI Investigation Engine

Evidence-based multi-document investigation system (not chat-with-PDF): hybrid retrieval, claim verification, contradiction detection, and abstention.

## Status

Phase 1 scaffold in progress. **Hosting:** Render Free + Neon Postgres + Qdrant Cloud.  
**Embeddings:** candidate `BAAI/bge-small-en-v1.5` via fastembed — **not finalized** until RSS benchmarks pass under Render’s 512 MB limit.

See `docs/FREE_TIER_NOTES.md` and `docs/DESIGN_DECISIONS.md`.

## Quick start (local)

```bash
uv sync --all-groups
cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000
```

Health: `GET /api/health`  
Ready: `GET /api/health/ready` (requires reachable `DATABASE_URL`; defaults to in-memory SQLite)

```bash
make test
make lint
make typecheck
make bench   # FastAPI + FastEmbed RSS / latency → docs/evidence/
```

## Free-tier demo notes

Render Free sleeps after 15 minutes of inactivity (~1 minute cold start). Documented and acceptable under the assignment. Persistent state lives in Neon and Qdrant, not the container filesystem.
