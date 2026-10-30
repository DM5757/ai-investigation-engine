# Progress

## Phase 0 — Complete

Render Free + Neon + Qdrant. Northflank rejected (card).

## Phase 1 — Complete (2026-10-29)

- Local quality + 512 MB container bench (peak **284.6 MiB**)
- Public URL: https://ai-investigation-engine-scyz.onrender.com
- Evidence: `docs/evidence/phase1.txt`, `docs/evidence/phase1_deploy.txt`

## Phase 2 — Complete (2026-10-29)

Parsing, chunking, duplicates, document lifecycle (DOC-1 to DOC-5).

## Phase 3 — Complete (2026-10-29)

Hybrid retrieval (VEC-1 to VEC-4).

## Phase 4 — Complete (2026-10-29)

LLM gateway + investigation engine (RAG-1 to RAG-8).

## Phase 5 — Complete (2026-10-29)

Ask API + vanilla JS UI.

## Hotfix — Neon / Psycopg 3 (2026-10-29)

Normalize `postgresql://` → `postgresql+psycopg://`.

## Phase 6 — Complete (2026-10-29 evening) — DATA-1 ≥50k verified

- Measured 2026-10-30: ACTIVE **55,081**, FAILED **0**, Qdrant **56,890**, `meets_data1_50k: true`
- Chunk gap explained: total chunk_rows 56,900 = ACTIVE 56,890 + DELETED-doc rows 10
- Evidence: `docs/evidence/dataset_counts.json`, `docs/evidence/bulk_ingest.json`

## Phase 7 — Evaluation

- Full-corpus retrieval `full55k_retrieval_v1`: n_scored=91; dense R@10 0.890; hybrid MRR 0.919
- Controlled answer `full55k_answer_v1` (n=12): investigation provider-limited mid-run
- Report: `docs/EVALUATION_REPORT.md`

## Post-submission quality — Complete (2026-10-30)

- Per-request LLM budget reset; budget/provider failure → explicit `llm_unavailable` (no fake partial essays)
- Question-conditioned sufficiency + claim filtering; colony abstention verified scripted
- Relative retrieval floor, phrase-aware rerank, citation prune-to-answer
- `/api/version` includes `git_commit` (Render verified `0036003…`)
- Default wall-clock budget raised **120→300s** for Render Free latency (follow-up deploy)
- Early tag `submission-2026-10-29` @ `1ab164d` **unchanged**

## Human actions still required

1. Own interview defense of AI-assisted work.
2. After wall-clock 300s deploy, re-check Roanoke airport on public URL when providers are healthy.
3. Optional: quota window for full investigation answer eval without early stop.
