# AI Usage Report

**Project:** Applied AI Investigation Engine  
**Repository:** https://github.com/DM5757/ai-investigation-engine  
**Report date:** 2026-10-29

## Disclosure

AI tools were used extensively during this assignment. This report discloses how they were used. The candidate remains responsible for the submitted code and for defending it in interview.

## Tools used

| Tool | Role |
| --- | --- |
| **Cursor Agent** (Composer / agent mode) | Primary implementation assistant across Phases 0–7: architecture drafting, Python modules, tests, scripts, deployment wiring, evaluation harness, documentation, debugging Neon/Qdrant/Render issues, and bulk-ingest acceleration |
| **Cursor IDE inline assist** | Small edits, renames, and local fixes |
| Web / provider docs (via agent tooling) | Free-tier verification for Render, Neon, Qdrant, Groq, Gemini |

## How AI helped

1. **Architecture and free-tier planning** — compared hosting options under a no-paid-card constraint; documented Render Free + Neon + Qdrant Cloud.
2. **Implementation** — FastAPI app, SQLAlchemy/Alembic lifecycle, FastEmbed + custom BM25 hybrid retrieval, custom reranker, hand-written investigation state machine, static UI, evaluation harness.
3. **Debugging** — Psycopg 3 dialect fix for Neon; Windows App Control / PyArrow parquet streaming workaround; Render memory gating for FastEmbed; bulk-ingest lock and batching.
4. **Evaluation** — metrics, question-set builder (HotpotQA + synthetic), retrieval and answer comparison runners.
5. **Documentation** — README, design notes, requirements traceability, evaluation report drafts.

## What you should fill in (candidate)

> Complete the following honestly before submission. Do not leave placeholder claims.

### Independent verification I performed

- [ ] I read and can explain `app/ingestion/lifecycle.py` document state machine
- [ ] I read and can explain `app/retrieval/hybrid.py` + custom BM25 / reranker
- [ ] I read and can explain `app/investigation/engine.py` tool loop
- [ ] I ran local tests / live smoke myself and recorded results
- [ ] I verified the public Render demo with my own browser/API calls
- [ ] I reviewed secrets handling (no keys in git; admin token for mutating APIs)

### Changes I made independently (examples)

_Describe concrete edits, refactors, or decisions you made without AI, or after rejecting AI suggestions:_

- …
- …

### Areas I still want to strengthen before interview

- …

## Integrity statement

AI assistance does not replace ownership. Fabricated evaluation numbers, fake ingestion counts, or undocumented paid infrastructure would violate the assignment. Measured evidence lives under `docs/evidence/` and `eval/results/`.
