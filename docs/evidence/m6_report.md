# Milestone 6 — Answer quality, evaluation validity, adaptive synthesis

**Corpus:** ACTIVE 55,081 (unchanged).  
**Held-out:** test split 62 questions. Dev (32) used only for selecting changes.  
**Preserved M5 baseline:** `eval/results/m5_answer_v2__*` (not overwritten).

## Evaluation validity (unchanged metrics)

See `docs/evidence/m6_eval_audit.md`. Metrics were audited, not loosened.

Primary failure modes under M5: verbose quote dumps vs Hotpot short gold (~2.7 tokens), weak claim/span selection (~14% gold containment), citation F1 diluted by insufficient rows.

## Held-out test comparison (same 62 questions, ACTIVE 55,081)

| Config | n answer | Token F1 | Cite F1 | Cite F1 (answered) | Abstention | Contradiction | Mean lat (s) | Mean LLM calls | Mean tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M5 investigation (`m5_answer_v2`) | 61 | 0.031 | 0.279 | — | 0.50 | 0.50 | 0.82 | 0.00 | 0 |
| M6 deterministic (`m6_test_det_v1`) | 62 | **0.080** | 0.272 | 0.452 | **1.00** | 0.50 | **0.35** | 0.00 | 0 |
| M6 adaptive (`m6_test_adapt_v1`) | 62 | **0.153** | **0.309** | **0.519** | **1.00** | 0.50 | 2.20 | **0.37** | 452 |
| M6 baseline RAG (same run) | 62 | 0.092 | 0.427 | 0.427 | 0.00 | 0.00 | 0.14 | 0.00 | 0 |

Adaptive synthesis modes on test: **39 deterministic / 23 LLM**. Gold-span containment among answerable items: **5/58 → 14/58**.

Artifacts: `eval/results/m6_test_det_v1__*`, `eval/results/m6_test_adapt_v1__*`.

## What changed

1. Short evidence-grounded span extraction (`app/investigation/answer_span.py`) for dates, comparisons, markers, abbreviations, roles, states.
2. Adaptive routing: high-confidence spans stay deterministic; uncertain questions use verified LLM synthesis (trace `synthesis_mode`).
3. Question-gated temporal conflicts; imperative focus phrases stripped; redacted/unnamed approver → insufficient.
4. Multi-hop date/country spans attach first-hop claims so required supporting docs remain cited.

## Limitations

- Exact match remains ~0 (Hotpot gold formatting / aliases).
- Contradiction detection still 0.5 on the two test items (root-cause pair not always conflicting by polarity rules).
- Baseline citation F1 stays higher because it always answers and dumps snippets (no abstention).
- Free-tier LLM quotas still constrain adaptive polish at scale.
