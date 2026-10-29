# Phase 7 notes — Evaluation

## Modules

1. `eval/metrics.py` — Recall@K, MRR, F1, citation accuracy, abstention helpers
2. `eval/run_eval.py` — resumable dense/hybrid + baseline/investigation runners
3. `scripts/build_eval_questions.py` — Hotpot parquet + synthetic_truth → ≥40 questions
4. `eval/configs/*.json` — named experiment configs
5. `docs/EVALUATION_REPORT.md` — methodology, tables, failure analysis

## Interview map

1. Why preliminary metrics must not be sold as full-corpus performance
2. Why Hotpot gold titles may not resolve until ingest reaches them
3. Why investigation recorded 0 LLM calls in `prelim_answer_v1` (degraded path)
4. How DOC-6 chunking comparison differs from retrieval-mode comparison

## Limits

- Re-run after ACTIVE ≥ 50k
- Contradiction/abstention: deterministic PASS; live status labeling still weak
- Investigation answer eval heavily rate-limited (Groq 200k TPD); use pause + stop-after flags
- Candidate must complete AI usage independent-verification checklist
- Early tag `submission-2026-10-29` preserved; continuation work lands on `main`
