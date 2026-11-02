# AI Investigation Engine

Evidence-based multi-document investigation system: hybrid retrieval, claim verification, contradiction detection, and abstention when evidence is insufficient. This is not a chat-with-PDF wrapper.

**Live demo:** https://ai-investigation-engine-scyz.onrender.com  
**Repository:** https://github.com/DM5757/ai-investigation-engine

## Problem

Given a large document corpus, answer questions that may require combining multiple sources, detecting conflicts, or admitting that the evidence is not there. Answers must cite real retrieved text; unsupported conclusions should not be invented.

## What is verified

| Signal | Measured value | Evidence |
| --- | --- | --- |
| ACTIVE documents | **55,081** | `docs/evidence/dataset_counts.json` + live `/api/stats` |
| FAILED records | **0** | same |
| Qdrant points | **56,890** (= ACTIVE chunk rows) | same |
| Automated tests | **200** passing (1 live test deselected by default) | `pytest` |
| Retrieval eval | **91** scored questions; dense R@10 **0.890**; hybrid MRR **0.919** | `docs/EVALUATION_REPORT.md` |
| Answer eval (test split) | **62** questions; adaptive token F1 **0.183**; cite F1 **0.365**; abstention **1.0**; contradiction **1.0** | `eval/results/m7_test_adapt_v3__*` |
| Reviewer demos | factual, multi-doc comparison, multi-hop, contradiction, abstention | `docs/evidence/reviewer_demo_cases.md` + Investigate tab samples |
| Behavioral core | Milestone 7 (`611b0d4`) | production smoke 10/10 |
| UI / presentation | Milestone 8 (reviewer demo) | this repo + live `/` |

Trust measured artifacts over narrative claims. Do not claim ≥50k indexed documents unless `dataset_counts.json` reports `meets_data1_50k: true`. Curated smoke success is **not** overall accuracy — held-out token F1 is **0.183**.

## How the pipeline works

1. **Ingest** — parse TXT/MD/PDF/DOCX/HTML/JSONL/CSV; normalize; chunk; exact/near-dup detect; persist versions in Neon; upsert dense + sparse vectors to Qdrant.
2. **Retrieve** — FastEmbed `bge-small-en-v1.5` dense search + custom BM25 sparse; RRF / weighted fusion; custom feature-based reranker (coverage, title/heading, entity/number, proximity, MMR, per-doc cap).
3. **Investigate** — hand-written stages (deterministic plan → seed/bridge retrieval → extract/verify → sufficiency → synthesize). When seed evidence already covers the asked entities, the LLM tool loop is skipped. Synthesis is adaptive: high-confidence short spans stay deterministic; uncertain questions use verified LLM phrasing. Mode (`deterministic` \| `llm`) is recorded in the trace.
4. **Respond** — answered / partial / conflicting / insufficient / `llm_unavailable`, with quote-checked citations when an answer is produced.

## Custom algorithms

- **BM25 sparse encoder** — stable CRC32 term ids, document TF weights, corpus `avgdl` from index stats (`app/retrieval/bm25_sparse.py`).
- **Feature reranker** — linear explainable features plus near-dup collapse and per-document caps (`app/retrieval/reranker.py`).
- **Investigation state machine** — planner, tools, quote verification, contradiction candidates, question-conditioned sufficiency (`app/investigation/`).

## Architecture

| Layer | Choice |
| --- | --- |
| API / UI | FastAPI + static HTML/CSS/JS (no SPA framework) |
| Metadata DB | Neon PostgreSQL (SQLAlchemy 2 + Alembic, Psycopg 3) |
| Vectors | Qdrant Cloud (named dense + sparse) |
| Embeddings | `BAAI/bge-small-en-v1.5` via FastEmbed |
| LLM | Groq primary, Gemini fallback (OpenAI-compatible gateway) |
| Hosting | Render Free (512 MB); state in Neon + Qdrant |

Further detail: `docs/DESIGN_DECISIONS.md`, `docs/DATABASE_DESIGN.md`, `docs/FREE_TIER_NOTES.md`, `docs/DEPLOYMENT.md`.

## Try the live demo

1. Open https://ai-investigation-engine-scyz.onrender.com (cold start after idle can take ~1 minute).
2. Use a **Sample investigation** chip or type a question on the Investigate tab, then **Run investigation**.
3. Inspect status, answer, supporting citations (click to scroll), conflicts, and stage latency.
4. Open **Corpus** for live ACTIVE counts and **Evaluation** for held-out metrics with denominators and limitations.
5. Confirm deploy SHA via `/api/version`.

Document mutation routes require `X-Admin-Token` and are not intended for anonymous public use.

## Local setup

```bash
uv sync --all-groups
cp .env.example .env
# Fill DATABASE_URL, QDRANT_*, GROQ_API_KEY / GEMINI_API_KEY, ADMIN_TOKEN
uv run uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/`.

```bash
make test        # unit/integration (live LLM tests deselected by default)
make lint
make typecheck
make test-live   # optional; consumes free-tier quota
```

## Data ingestion

Corpus build and bulk index run off-host (Render disk is ephemeral):

```bash
uv run python scripts/build_corpus.py --target 55000
uv run python scripts/generate_synthetic.py
uv run python scripts/ingest_synthetic.py
uv run python scripts/pilot_ingest.py
uv run python scripts/bulk_ingest.py --max-docs 55000 --batch-size 16 --checkpoint-every 50
uv run python scripts/verify_counts.py   # writes docs/evidence/dataset_counts.json
```

Windows overnight resume: `scripts/watch_bulk_ingest.ps1` (single writer; file lock; default batch 16).

## Evaluation

```bash
uv run python scripts/build_eval_questions.py --require-active
uv run python eval/run_eval.py --configs dense_only,hybrid_rrf --split all --retrieval-only --scorable-only
uv run python eval/run_eval.py --configs baseline_rag,full_investigation --split test --scorable-only \
  --pause-s 2 --stop-after-llm-unavailable 3
```

Always report **n_total / n_scored / exclusions / provider skips**.  
UI summary is served from `app/data/published_eval.json` (sourced from committed `eval/results/`).  
Report: `docs/EVALUATION_REPORT.md` · Results: `eval/results/` · DOC-6: `eval/results/chunking_comparison.*`

## Known limitations

- Render Free cold starts remain; cold `/api/health` can take ~1 minute after idle.
- Groq free-tier daily quota / Gemini RPM can force `llm_unavailable` when the LLM path is required.
- Held-out token F1 is **0.183** and exact match ~0 — quote-grounded answers often differ from Hotpot short gold strings.
- Multi-hop recall and general answer accuracy still leave room for improvement beyond the curated demo set.
- Sample chips only cover verified production cases; arbitrary questions may abstain or degrade honestly.

## Documentation index

| Doc | Purpose |
| --- | --- |
| `docs/assignment/…` | Official specification |
| `docs/PROGRESS.md` | Phase status and verified milestones |
| `docs/REQUIREMENTS_TRACEABILITY.md` | Requirement → evidence map |
| `docs/EVALUATION_REPORT.md` | Metrics and analysis |
| `docs/AI_USAGE_REPORT.md` | AI assistance disclosure |
| `docs/evidence/` | Measured artifacts |
| `docs/phase_notes/` | Per-phase implementation notes |

## License / data

HotpotQA paragraphs: **CC BY-SA 4.0** (attribute authors; share-alike for derivatives). Synthetic enterprise docs are project-generated.
