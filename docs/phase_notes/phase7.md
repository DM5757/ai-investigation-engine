# Phase 7 notes — Evaluation

## Modules

1. `eval/metrics.py` — Recall@K, MRR, F1, citation accuracy, abstention helpers
2. `eval/run_eval.py` — resumable dense/hybrid + baseline/investigation runners
3. `scripts/build_eval_questions.py` — Hotpot parquet + synthetic_truth → ≥40 questions
4. `eval/configs/*.json` — named experiment configs
5. `docs/EVALUATION_REPORT.md` — methodology, tables, failure analysis

## Design notes

- Do not present pre-50k preliminary metrics as full-corpus performance.
- Hotpot gold titles only resolve once those documents are ACTIVE in Neon.
- Investigation rows with 0 LLM calls indicate a degraded path, not a successful answer.
- DOC-6 chunking comparison is distinct from retrieval-mode (dense vs hybrid) comparison.
- Always publish n_total / n_scored / exclusions / provider skips.

## Limits

- Full-corpus retrieval `full55k_retrieval_v1` scored n=91 (dense R@10 0.890; hybrid MRR 0.919).
- Contradiction/abstention: deterministic tests PASS; live status labeling remains quota-sensitive.
- Investigation answer eval is heavily rate-limited (Groq TPD/TPM); use pause + stop-after flags.
- Early tag `submission-2026-10-29` preserved; continuation work lands on `main`.
