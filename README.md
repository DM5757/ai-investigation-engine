# AI Investigation Engine

Evidence-based **multi-document investigation** system (not chat-with-PDF): hybrid retrieval, claim verification, contradiction detection, and abstention when evidence is insufficient.

**Live demo:** https://ai-investigation-engine-scyz.onrender.com  
**Repository:** https://github.com/DM5757/ai-investigation-engine

## What it does

- Ingests documents in multiple formats (TXT, MD, PDF, DOCX, HTML, JSONL, CSV)
- Chunks, deduplicates, and indexes into **Neon Postgres** (metadata SoT) + **Qdrant Cloud** (dense + sparse vectors)
- Retrieves with **hybrid search** (FastEmbed `bge-small-en-v1.5` + custom BM25) and a **custom feature-based reranker**
- Runs a **hand-written multi-step investigation** (plan → tools → synthesize → verify citations)
- Surfaces contradictions and abstains rather than inventing facts
- Ships a vanilla JS UI (Ask / Documents / Stats / Evaluation / Health)

## Architecture

| Layer | Choice |
| --- | --- |
| API / UI | FastAPI + static HTML/CSS/JS |
| Metadata DB | Neon PostgreSQL (SQLAlchemy 2 + Alembic, Psycopg 3) |
| Vectors | Qdrant Cloud (named dense + sparse) |
| Embeddings | `BAAI/bge-small-en-v1.5` via FastEmbed |
| LLM | Groq primary, Gemini fallback (OpenAI-compatible gateway) |
| Hosting | Render Free (512 MB); state in Neon + Qdrant |

See `docs/DESIGN_DECISIONS.md`, `docs/ARCHITECTURE.md` (if present), `docs/DATABASE_DESIGN.md`, `docs/FREE_TIER_NOTES.md`, `docs/DEPLOYMENT.md`.

## Quick start (local)

```bash
uv sync --all-groups
cp .env.example .env
# Fill DATABASE_URL, QDRANT_*, GROQ_API_KEY / GEMINI_API_KEY, ADMIN_TOKEN
uv run uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/`.

- Ask: `POST /api/query` (public, rate-limited)
- Documents: mutating routes require `X-Admin-Token`
- Health: `GET /api/health`, `GET /api/health/ready`, `GET /api/version`

```bash
make test        # unit/integration (live LLM tests deselected by default)
make lint
make typecheck
make test-live   # optional; consumes free-tier quota
```

## Data ingestion

Corpus build and bulk index (off-host; Render disk is ephemeral):

```bash
uv run python scripts/build_corpus.py --target 55000
uv run python scripts/generate_synthetic.py
uv run python scripts/ingest_synthetic.py
uv run python scripts/pilot_ingest.py
uv run python scripts/bulk_ingest.py --max-docs 55000 --batch-size 16 --checkpoint-every 50
uv run python scripts/verify_counts.py   # writes docs/evidence/dataset_counts.json
```

Windows overnight resume: `scripts/watch_bulk_ingest.ps1` (single writer; file lock; default batch 16).

**Honesty rule:** Do not claim ≥50,000 indexed documents unless `docs/evidence/dataset_counts.json` reports `meets_data1_50k: true`.

## Evaluation

```bash
# Prefer Hotpot questions whose gold titles are already ACTIVE in Neon:
uv run python scripts/build_eval_questions.py --require-active
uv run python eval/run_eval.py --configs dense_only,hybrid_rrf --split all --retrieval-only --scorable-only
uv run python eval/run_eval.py --configs baseline_rag,full_investigation --split test --scorable-only \
  --pause-s 2 --stop-after-llm-unavailable 3
```

Always report **n_total / n_scored / exclusions / provider skips** (do not hide unresolved golds or rate-limit skips).  
Report: `docs/EVALUATION_REPORT.md` · Results: `eval/results/` · DOC-6: `eval/results/chunking_comparison.*`

## Deployment

Render Free via `Dockerfile` + `render.yaml`. Persistence is external (Neon + Qdrant). The service sleeps after ~15 minutes idle (~1 minute cold start) — allowed by the assignment when documented.

Required secrets on Render: `DATABASE_URL`, `QDRANT_URL`, `QDRANT_API_KEY`, `GROQ_API_KEY` / `GEMINI_API_KEY`, `ADMIN_TOKEN`. Keep `EMBEDDING_ENABLED_AT_STARTUP` aligned with measured 512 MB headroom (model may lazy-load on first query).

## Major technical decisions

1. **Render Free over Northflank/HF Spaces** — no payment card; 512 MB requires measured embedding RSS.
2. **Neon + Qdrant** — ephemeral PaaS disk cannot hold the corpus; Postgres is source of truth.
3. **Custom BM25 + reranker** — assignment requires a non-library-only ranking component.
4. **Hand-written investigation state machine** — no LangChain/LlamaIndex; interview-explainable tool loop.
5. **Batched bulk ingest** — embed/upsert batches to approach the 50k-record requirement under free-tier latency.

## Known limitations

- Full HotpotQA-scale indexing may still be in progress at submission; always trust `dataset_counts.json`.
- Preliminary evaluation metrics are labeled when the active corpus is &lt; 50k.
- Render cold starts and free LLM rate limits affect demo latency.
- Contradiction detection is strong in unit/scripted tests; live contradiction rates depend on retrieval coverage and LLM availability.
- Windows App Control can block `datasets`/pandas; corpus build uses PyArrow parquet streaming.

## Documentation index

| Doc | Purpose |
| --- | --- |
| `docs/assignment/…` | Official specification |
| `docs/PROGRESS.md` | Phase status |
| `docs/REQUIREMENTS_TRACEABILITY.md` | Requirement → evidence map |
| `docs/EVALUATION_REPORT.md` | Metrics and analysis |
| `docs/AI_USAGE_REPORT.md` | AI assistance disclosure |
| `docs/evidence/` | Measured artifacts |

## License / data

HotpotQA paragraphs: **CC BY-SA 4.0** (attribute authors; share-alike for derivatives). Synthetic enterprise docs are project-generated.
