# AI Investigation Engine

Evidence-based multi-document investigation system (not chat-with-PDF): hybrid retrieval, claim verification, contradiction detection, and abstention.

## Status

Phase 5 complete (Ask API + static UI). **Live demo (Phase 1 health):** https://ai-investigation-engine-scyz.onrender.com  
**Hosting:** Render Free + Neon Postgres + Qdrant Cloud.  
**Embeddings:** `BAAI/bge-small-en-v1.5` via fastembed — provisionally approved (Docker 512 MB peak **284.6 MiB**).

See `docs/FREE_TIER_NOTES.md` and `docs/DESIGN_DECISIONS.md`.

## Quick start (local)

```bash
uv sync --all-groups
cp .env.example .env
# Set ADMIN_TOKEN for document upload/update/delete/reindex
uv run uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/` for the UI tabs: **Ask** | **Documents** | **Corpus stats** | **Evaluation** | **Health**.

- Ask: `POST /api/query` (public, rate-limited)
- Documents: mutating calls require header `X-Admin-Token` matching `ADMIN_TOKEN` (UI keeps the token in a JS memory variable, not localStorage)
- Health: `GET /api/health`, `GET /api/health/ready`, `GET /api/version`

```bash
make test
make lint
make typecheck
make bench   # FastAPI + FastEmbed RSS / latency → docs/evidence/
```

## Free-tier demo notes

Render Free sleeps after 15 minutes of inactivity (~1 minute cold start). Documented and acceptable under the assignment. Persistent state lives in Neon and Qdrant, not the container filesystem. Phase 5 document/query routes are verified locally; do not assume Render has full Qdrant/LLM wiring for every new endpoint.
