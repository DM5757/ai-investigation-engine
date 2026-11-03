# AI Investigation Engine

Evidence-based multi-document investigation: hybrid retrieval, quote-checked citations, contradiction detection, and honest abstention when evidence is insufficient. This is **not** a chat-with-PDF wrapper.

**Live demo:** https://ai-investigation-engine-scyz.onrender.com  
**Repository:** https://github.com/DM5757/ai-investigation-engine

## What it does

Given a large indexed corpus, the engine:

1. Retrieves relevant passages (dense + custom BM25 sparse, optional rerank).
2. Extracts and verifies claims against source text.
3. Synthesizes a short answer **only** when evidence supports it.
4. Returns citations you can inspect, flags conflicts, or abstains.

Production uses the **legacy investigation pipeline**. An experimental passage reader exists in the repo behind a feature flag and is **disabled by default** — it is not advertised as production-ready.

## Verified production signals

| Signal | Value | Evidence |
| --- | --- | --- |
| ACTIVE documents | **55,081** | `docs/evidence/dataset_counts.json`, live `/api/stats` |
| Qdrant points | **56,890** | same |
| Automated tests | unit/integration via `pytest` | CI on `main` |
| Retrieval (full corpus) | dense R@10 **0.890**; hybrid MRR **0.919** (n=91) | `docs/EVALUATION_REPORT.md` |
| Held-out answers (legacy test, cite-stripped) | token F1 **~0.22**; abstention **1.0**; contradiction **1.0** (n=62) | `eval/results/m7_test_adapt_v3__*` |
| Reviewer samples | factual / multi-doc / multi-hop / conflict / abstain | Investigate tab + `docs/evidence/reviewer_demo_cases.md` |

Curated smoke success is **not** overall accuracy. Do not treat incomplete experimental benchmarks as production quality.

## Try the live demo

1. Open the demo URL (Render Free cold start after idle can take ~1 minute).
2. Expand **How to use this demo**, pick a **sample investigation**, then **Run investigation**.
3. Inspect status, answer, citation chips → source quotes, conflicts, and investigation steps.
4. Open **Corpus** / **Evaluation** / **Health** for live counts, held-out metrics, and deploy SHA (`/api/version`).

Samples call the real `/api/query` API — answers are not hardcoded in the browser.

## Architecture

| Layer | Choice |
| --- | --- |
| API / UI | FastAPI + static HTML/CSS/JS |
| Metadata | Neon PostgreSQL (SQLAlchemy 2 + Alembic) |
| Vectors | Qdrant Cloud (dense + sparse) |
| Embeddings | `BAAI/bge-small-en-v1.5` (FastEmbed) |
| LLM | Groq primary, Gemini fallback |
| Hosting | Render Free (512 MB); durable state in Neon + Qdrant |

**Custom pieces:** BM25 sparse encoder, feature-based reranker, investigation state machine with quote verification (`app/retrieval/`, `app/investigation/`).

More detail: `docs/DESIGN_DECISIONS.md`, `docs/DATABASE_DESIGN.md`, `docs/DEPLOYMENT.md`, `docs/FREE_TIER_NOTES.md`.

## Local setup

```bash
uv sync --all-groups
cp .env.example .env
# Fill DATABASE_URL, QDRANT_*, GROQ_API_KEY / GEMINI_API_KEY, ADMIN_TOKEN
uv run uvicorn app.main:app --reload --port 8000
```

```bash
make test        # unit/integration (live LLM deselected by default)
make lint
make typecheck
```

## Evaluation (honest summary)

| Track | Status | Notes |
| --- | --- | --- |
| Legacy / Milestone 7 held-out | **Published** | Modest F1; strong abstention & contradiction on the curated set |
| Phase A integrity fixes | **Published** | Cite-stripped rescoring; retrieval mode comparison |
| Passage-reader experiments (dev) | **Development only** | Flag off in production; see `docs/evidence/phase_*` |
| Sealed Hotpot unlock (`sealed_final_v1`) | **Incomplete / inconclusive** | Stopped on free-tier quotas; **not** a final accuracy number — `docs/evidence/sealed_final_v1_status.md` |

```bash
uv run python eval/run_eval.py --configs dense_only,hybrid_rrf --split all --retrieval-only --scorable-only
```

Always report **n_total / n_scored / exclusions / provider skips**.

## Known limitations

- Render Free cold starts (~1 minute after idle).
- Free-tier LLM quotas can yield `llm_unavailable` (surfaced honestly; no invented fill-in).
- Held-out answer F1 remains modest versus short Hotpot gold strings.
- Multi-hop completeness is imperfect on hard questions.
- Experimental passage reader is **not** enabled in production.

## Documentation

| Doc | Purpose |
| --- | --- |
| `docs/EVALUATION_REPORT.md` | Metrics and analysis |
| `docs/PROGRESS.md` | Phase history |
| `docs/AI_USAGE_REPORT.md` | AI assistance disclosure |
| `docs/evidence/` | Measured artifacts (including incomplete sealed status) |
| `docs/assignment/` | Official specification |

## License / data

HotpotQA paragraphs: **CC BY-SA 4.0**. Synthetic enterprise docs are project-generated. Submission tag `submission-2026-10-29` is preserved.
