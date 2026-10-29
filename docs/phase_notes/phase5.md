# Phase 5 notes — Ask API + vanilla JS UI

## Key modules (interview map)

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

## Interview questions

1. Why mutating document routes need constant-time token compare, while `/api/query` is public?
2. How does the UI avoid XSS when rendering answers and chunk text?
3. What happens on `/api/query` when no LLM keys are configured?
4. How are retrieval `mode` overrides constrained, and what is the API default?
5. Where do in-memory `/api/metrics` counters live, and what do they *not* survive?
6. Why is `/api/eval/runs` an honest empty stub instead of fake scores?

## Limits

- Qdrant Cloud remote still unverified; bm25_avgdl default; CRC32 collisions pending; retrieval eval pending.
- Render public URL may not expose fully wired Phase 5 cloud deps — local TestClient is the Phase 5 proof.
- SSE streaming intentionally skipped.
