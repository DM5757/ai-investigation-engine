# Progress

## Phase 0 — Complete

Render Free + Neon + Qdrant. Northflank rejected (card).

## Phase 1 — Local verification complete; deploy pending

### Passed (recorded in `docs/evidence/`)

- Docker Engine 29.7.2 accessible
- Image build + run; `/api/health`, `/api/health/ready`, `/api/version`
- ruff / mypy / pytest (5 passed)
- Container bench under **512 MB**: peak **284.6 MiB**, no OOM, embed p50 **~6.3 ms**

### Remaining to close Phase 1

1. First git commit + push to GitHub
2. Deploy Render Free web service → public URL
3. Save `curl` of live `/api/health` to `docs/evidence/phase1_deploy.txt`

**Do not start Phase 2 until the public URL evidence exists.**

## HUMAN ACTION REQUIRED — Render deploy

See chat instructions (commit/push + Render dashboard). Set at least:

- `DATABASE_URL` (SQLite file URL is OK for skeleton only; prefer Neon for persistence)
- Optional for skeleton: leave `EMBEDDING_ENABLED_AT_STARTUP=false`
- Keep `ENABLE_BENCH_ENDPOINTS=false` on Render
