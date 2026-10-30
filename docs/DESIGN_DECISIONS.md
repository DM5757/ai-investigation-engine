# Design decisions (Phase 0 draft)

Format for each decision: **selection**, **why**, **alternatives**, **why-not**, **trade-offs and limits**, **free-tier fit (verified date)**, **effect on maintainability / scalability / explainability**.

Status: **Hosting = Render Free**. Phase 1 container gate under **512 MB** passed (`docs/evidence/container_512m_bench.json`, peak **284.6 MiB**, no OOM). Embedding `fastembed`/`bge-small` is approved for Render under measured headroom; keep bench endpoints off in production. Corpus scale verified ACTIVE **55,081** (`docs/evidence/dataset_counts.json`).

---

## D13 (revised). Application hosting

- **Selection:** Deploy the FastAPI + static UI on **Render Free** web service (Docker or native Python). Public `onrender.com` URL. Persistence remains **Neon + Qdrant** (not local disk).
- **Why:** Owner’s Northflank account requires a payment card (rejected). Render Free needs no paid plan, supports Python/FastAPI/Docker, gives a public URL, and sleep-after-15-min is acceptable under assignment §4 if documented.
- **Alternatives:** Northflank Sandbox; Hugging Face Docker Spaces; Koyeb Free; Oracle Always Free; Cloud Run; Railway; Fly.io.
- **Why-not:**
  - **Northflank:** card required on owner account — **rejected** (28 Oct 2026).
  - **HF Spaces Docker/Gradio:** paid plan — **disallowed**.
  - **Koyeb Free:** similar 512 MB class; peer fallback.
  - **Fly.io / Railway Free:** not viable free demo hosts for this project.
  - **Cloud Run:** billing account / overage risk.
  - **Oracle:** more RAM but account friction; fallback if 512 MB cannot work even after measured embedding contingency.
- **Trade-offs and limits:** **512 MB RAM / 0.1 CPU**; sleep + ~1 min cold start; ephemeral disk; 750 Free instance-hours/month. In-process BGE-small may not fit — embedding decision deferred to Phase 1 benchmarks. Bulk ingest off-host.
- **Free-tier fit:** Verified 28 Oct 2026 — [Render free docs](https://render.com/docs/free).
- **Maintainability / scalability / explainability:** Sleep/cold-start, Neon+Qdrant persistence, and keep-alive trade-offs must remain explicit in ops docs.

**Fallback:** Koyeb Free → Oracle Always Free if measured needs exceed 512 MB after documented contingencies.

---

## D4. Metadata and persistence — Postgres

- **Selection:** **Neon Free** via SQLAlchemy 2.0 + Alembic; SQLite for local unit tests only.
- **Why:** Free PaaS disks are ephemeral; Neon provides durable Postgres with **1 GB/project** storage (as of Oct 2026 changelog) and enough CU-hours for a demo that scales to zero.
- **Alternatives:** Supabase Free; Render Free Postgres; Koyeb Free Postgres; SQLite on a volume; self-hosted Postgres on Oracle.
- **Why-not:** Render Free Postgres expires after 30 days; Koyeb Free DB only 5 active hours/month; Supabase Free has 500 MB and week-long pause; SQLite on free hosts does not survive redeploys without paid disks.
- **Trade-offs:** Cold starts after 5 min idle; storage discipline (text once per document, chunk offsets not full duplicate text in PG).
- **Free-tier fit:** Verified 28 Oct 2026 — [Neon plans](https://neon.com/docs/introduction/plans).
- **Explainability:** Clear source-of-truth vs derived index; transactions for lifecycle states.

---

## D3. Vector database

- **Selection:** **Qdrant Cloud Free** in production; embedded Qdrant for local tests. One collection with named **dense** + **sparse** vectors.
- **Why:** Purpose-built hybrid support, payload filters, deletes-by-filter, sparse IDF modifier. Free cluster is enough for ~50k–100k short Hotpot chunks if footprint is measured and `on_disk` used as needed.
- **Alternatives:** pgvector on Neon; Pinecone; Weaviate; Chroma; self-host Qdrant on Oracle.
- **Why-not:** Neon 1 GB cannot comfortably hold full text + 384-d vectors + HNSW + BM25 for 50k+ chunks; Pinecone free limits and weaker sparse control; Chroma persistence on ephemeral hosts is weak.
- **Trade-offs:** Two stores to reconcile; free cluster suspend/delete on long inactivity; 1 GB RAM / 4 GB disk hard caps.
- **Free-tier fit:** Verified 28 Oct 2026 — [Create a Cluster](https://qdrant.tech/documentation/cloud/create-cluster/).
- **Explainability:** Rebuild-from-Postgres story; sync protocol is a strength.

---

## D5. Embeddings (provisionally approved for Render Free)

- **Selection:** **`BAAI/bge-small-en-v1.5`** via **`fastembed`** (ONNX). Model baked into Docker image (`FASTEMBED_CACHE_PATH=/app/model_cache`). Bulk ingest still runs off-host; query encoding can run in-process on Render.
- **Why:** Measured under Docker `--memory=512m` on 28 Oct 2026: peak **284.6 MiB**, no OOM, embedding load **~440 ms** (cached), query p50 **~6.3 ms**. Free, local, 384-d, no per-token embedding quota.
- **Alternatives considered:** Qdrant Cloud Inference free models; smaller local encoders; remote APIs — deferred because local path met the 512 MB gate.
- **Trade-offs:** CPU latency on 0.1 vCPU under load; English-centric; image ~1.3 GB with baked model; Render sleep/cold start still applies.
- **Hard rules:** Custom BM25 + custom reranker remain; do not pay for larger hosts. Re-measure if dependencies grow.
- **Free-tier fit:** Verified locally in Linux container with 512 MB hard limit — see `docs/evidence/container_512m_bench.json`.
- **Explainability:** Baking the model, why RSS ≠ disk image size, and Neon/Qdrant for persistence.

---

## D6. LLM gateway (model IDs confirmed for wiring — 2026-10-29)

- **Selection:** OpenAI-compatible gateway. **Primary: Groq `openai/gpt-oss-120b`**. **Secondary: Gemini `gemini-3.5-flash-lite`** (alt `gemini-3.8-flash`) via `https://generativelanguage.googleapis.com/v1beta/openai/`. Config-only Groq alt: `qwen/qwen3.8-27b` (`GROQ_ALT_MODEL`).
- **Why:** Free quotas; docs confirm tool use + JSON mode on gpt-oss-120b; one OpenAI SDK client with `base_url`; automatic Groq→Gemini fallback; hand-written investigation state machine (no LangChain/LlamaIndex).
- **Alternatives:** OpenRouter free; Mistral/Cohere trials; local Ollama on free CPU; google-genai native SDK.
- **Why-not:** Master prompt’s Llama 3.3 70B **removed from Groq free/Developer** (shutdown 16 Aug 2026). Prefer OpenAI-compatible Gemini endpoint over a second SDK. Ollama quality/latency on free PaaS is poor.
- **Trade-offs:** Tight RPD/TPM; **never combine tools + `response_format` in one Groq call**; no parallel tool calls on gpt-oss-120b; free-tier prompts may train models — public/synthetic data only. Live Groq investigation smoke recorded in `docs/evidence/phase4_live_trace.json`; production probes remain quota-sensitive.
- **Free-tier fit:** Model IDs + tool/JSON capabilities recorded in `docs/evidence/llm_models_verified.txt` (2026-10-29).
- **Explainability:** Gateway, retries, budgets, degraded `llm_unavailable` with retrieved evidence, quote-verified citations.

---

## D1. Backend

- **Selection:** FastAPI + Pydantic v2 + Uvicorn; sync service layer.
- **Why:** Typed APIs, OpenAPI, familiar controller/DTO pattern for Spring-experienced owner.
- **Alternatives:** Flask, Django, fully async.
- **Why-not:** Flask lacks native validation; Django heavy; full async adds complexity without benefit at demo load.
- **Trade-offs:** Threadpool concurrency limits under load — documented.
- **Free-tier fit:** Yes.
- **Explainability:** Explicit layering; easy to debug live.

---

## D2. UI

- **Selection:** Static HTML + vanilla ES modules served by FastAPI. No Node build.
- **Why:** One deployable; no build toolchain; every line is inspectable.
- **Alternatives:** React/Vite; Streamlit/Gradio.
- **Why-not:** Build toolchain; Gradio/Streamlit weaker for citation/document UX and would push toward HF Spaces (paid).
- **Trade-offs:** Less polish (allowed by assignment).
- **Free-tier fit:** Yes.
- **Explainability:** Escape via `textContent`; no framework magic.

---

## D7. Keyword search

- **Selection:** Custom BM25 sparse encoder → Qdrant sparse vectors (IDF modifier).
- **Why:** Persistent, no in-memory inverted index on small hosts; genuinely custom (VEC-4 companion to reranker).
- **Alternatives:** Postgres `tsvector`; Elasticsearch; in-memory `rank_bm25`; Qdrant Cloud Inference `qdrant/bm25` alone.
- **Why-not:** Ready-made-only keyword path weakens custom requirement; ES not free-hostable; in-memory RAM cost.
- **Trade-offs:** `avgdl` fixed at bulk-build; document drift.
- **Free-tier fit:** Yes — compute on ingest machine; store sparse vectors in Qdrant Free.
- **Explainability:** Hand-derived BM25 formula and tests.

---

## D8. Hybrid fusion and reranker

- **Selection:** Custom RRF + weighted fusion; custom heuristic reranker (+ MMR / near-dup collapse / per-doc cap).
- **Why:** Mandatory custom algorithmic component (VEC-4); explainable features.
- **Alternatives:** Qdrant built-in fusion only; cross-encoder only.
- **Why-not:** Built-in fusion alone removes our custom centrepiece (may benchmark as baseline).
- **Trade-offs:** Feature weights tuned on **dev** only.
- **Free-tier fit:** CPU-only; fine on 0.5–2 vCPU.
- **Explainability:** Feature walkthrough and ablation modes.

---

## D9–D12 (unchanged intent)

- **D9 Parsing:** `pypdf`, `python-docx`, `bs4`+`lxml`, stdlib, `PyYAML`; reject AGPL PyMuPDF / heavy `unstructured` / OCR.
- **D10 No orchestration framework:** hand-written investigation state machine.
- **D11 Custom eval harness:** no RAGAS/DeepEval as primary.
- **D12 Tooling:** `uv`, Python ≥3.11, `ruff`, `mypy`, `pytest`, GitHub Actions, `gitleaks`.

Each dependency will be justified in one line when `pyproject.toml` is created in Phase 1.

---

## D14. Phase 2 document SoT layout

- **Selection:** Normalised full text stored on `document_versions.text`; chunk rows currently also store `text` plus offsets; `ChunkStore` Protocol with `QdrantChunkStore` + `InMemoryChunkStore` fallback for tests.
- **Why:** Versioned text makes update/diff clear; Protocol keeps lifecycle testable when host WDAC blocks embedded Qdrant gRPC (`cygrpc`).
- **Trade-offs:** Chunk text duplication vs master “offsets only in PG” ideal — acceptable for Phase 2; slim later if Neon storage pressure appears. In-memory store is tests-only; Render uses Qdrant Cloud URL when configured.
- **Free-tier fit:** No extra paid dependency.
- **Explainability:** Crash windows + `reconcile_session`; retrieval must filter `version == active_version`.

---

## D15. Phase 3 retrieval wiring

- **Selection:** Custom BM25 sparse (`zlib.crc32` term ids, TF-only weights) stored beside dense in Qdrant named vectors; fusion via custom RRF + weighted min-max; custom linear reranker. `DocumentLifecycle` optionally accepts `Bm25Encoder` to populate sparse on upsert. `active_versions` filter at store + defensive drop in `HybridRetriever`.
- **Why:** Matches D7/D8; hand-tested formulas satisfy VEC-4; stable ids survive restarts (unlike `hash()`).
- **Change vs Phase 2:** Search APIs added to `ChunkStore`; zero-vector default embed still allowed for old lifecycle tests, but semantic claims require FastEmbed (integration skips if model missing).
- **Trade-offs:** Fixed `bm25_avgdl` until bulk stats; adversarial dense used in sparse-rescue test (honest: not BGE failure).
- **Free-tier fit:** Same Qdrant Free + local ONNX path.
- **Explainability:** BM25 weight, RRF k=60, and why deleted docs never appear when the caller passes only the active version map.

---

## Decisions to revisit

1. ~~Confirm Northflank Sandbox~~ — rejected (card). Render Free live at `ai-investigation-engine-scyz.onrender.com`.
2. ~~Measure RSS with model loaded~~ — Docker 512m peak 284.6 MiB (passed).
3. Confirm Groq model tool-calling quality vs Qwen alternative on a 5-question smoke set.
4. Confirm Qdrant free cluster disk/RAM after 55k+ points with payload text.
5. Optionally slim chunk text out of Postgres once retrieval always loads text from version slices or Qdrant payload.
6. Compute corpus `avgdl` at bulk ingest and refresh sparse vectors if drift is large.
