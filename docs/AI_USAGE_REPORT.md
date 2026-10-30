# AI Usage Report

**Project:** Applied AI Investigation Engine  
**Repository:** https://github.com/DM5757/ai-investigation-engine  
**Report date:** 2026-10-29 (updated 2026-10-30)

## Disclosure

This project was built with **extensive AI assistance**. Cursor Agent (Composer / agent mode) was the primary co-pilot for architecture, implementation, debugging, evaluation, deployment wiring, and documentation across Phases 0–7 and post-submission quality work. This report describes how AI was used; it does not claim that every line was independently authored without assistance. Accountability for submitted artifacts, measured claims, and live demo behavior remains with the project owner.

## Tools used

| Tool | Role |
| --- | --- |
| Cursor Agent (Composer / agent mode) | Main assistant for design, code, tests, scripts, docs, free-tier deployment, and eval harness |
| Cursor IDE inline assist | Small local edits and quick fixes |
| Provider / product documentation (via agent tooling) | Checks against Render, Neon, Qdrant, Groq, and Gemini free-tier limits |

## How AI was used

AI helped compare free hosting options and settle on Render Free with Neon and Qdrant Cloud under a no-paid-card constraint. It drafted and iterated much of the application stack: document ingestion and lifecycle, hybrid retrieval (dense embeddings with custom BM25 and reranking), the investigation tool loop and LLM gateway, the FastAPI API and static UI, and the evaluation harness built on HotpotQA plus synthetic questions.

AI was also used heavily for debugging—including the Psycopg 3 / Neon dialect issue, Windows tooling and Parquet streaming workarounds, Render memory limits for FastEmbed, and Qdrant bulk-upsert timeouts—and for producing README, design notes, requirements traceability, and evaluation report drafts. Human direction set goals, constraints, and honesty rules (especially around measured corpus size and provider-limited evaluation); AI produced most of the concrete artifacts under those constraints.

## Integrity

Evaluation metrics and ingestion counts are taken from recorded artifacts under `docs/evidence/` and `eval/results/`, not from unverified estimates. As of the 2026-10-30 measurement, ACTIVE documents are **55,081** with `meets_data1_50k: true` (`docs/evidence/dataset_counts.json`). Known limitations—especially investigation answer evaluation constrained by free-tier LLM rate limits, and Render Free latency—are disclosed in `docs/EVALUATION_REPORT.md` and `docs/PROGRESS.md`. Fabricated scores, inflated corpus claims, or undisclosed paid infrastructure would violate the assignment. AI assistance does not replace accountability for what is published.
