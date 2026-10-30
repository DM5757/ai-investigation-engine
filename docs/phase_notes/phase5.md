# Phase 5 notes — Ask API + vanilla JS UI

## Key modules

1. `app.api.security.require_admin_token` — constant-time `X-Admin-Token` compare.
2. `app.api.ratelimit.TokenBucketLimiter` — per-IP query rate limit; optional `DailyCounter`.
3. `app.api.routes_documents` — thin multipart CRUD → `DocumentLifecycle`.
4. `app.api.routes_query` — rate-limit then `InvestigationEngine.investigate`; enrich `sources`.
5. `app.api.routes_stats` — `/api/stats`, `/api/metrics`, stub `/api/eval/runs`.
6. `app.deps` — process-scoped store/embedder/bm25/llm; per-request lifecycle + engine.
7. `app.schemas.query.QueryRequest` — whitelisted `mode` only.
8. `app.ui.static/` — Ask | Documents | Stats | Evaluation | Health (`textContent` only).

## API request lifecycle (documents)

`POST /api/documents` → `require_admin_token` → size/extension checks →
`DocumentLifecycle.add` (parse → dedup → persist → embed/sparse → Qdrant upsert → ACTIVE) →
`LifecycleResponse` (`outcome`, `document_id`, `status`, `message`, `near_duplicate_of`).

## API request lifecycle (query)

`POST /api/query` → token-bucket (per IP) → optional daily LLM cap → pin `retriever.default_mode` →
`InvestigationEngine.investigate` → enrich citations from chunk store/DB →
`QueryResponse` (+ `sources`, `missing_information`).

## Design notes

- Mutating document routes need constant-time token compare; `/api/query` is public and rate-limited.
- UI uses `textContent` to avoid XSS when rendering answers and chunk text.
- Missing LLM keys yield degraded status with evidence preview, not invented essays.
- Retrieval `mode` overrides are whitelisted; API default follows settings.
- In-memory `/api/metrics` counters do not survive process restart.
- `/api/eval/runs` is an honest empty stub rather than fabricated scores.

## Limits

- SSE streaming intentionally skipped.
- Production query quality depends on live Neon/Qdrant corpus + free LLM quotas.
