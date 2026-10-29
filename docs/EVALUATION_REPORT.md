# Evaluation Report

**Project:** Applied AI Investigation Engine  
**Date:** 2026-10-29  
**Corpus note:** Preliminary while ACTIVE &lt; 50k. Metrics use **transparent denominators**.

## 1. Why earlier runs scored only ~7 questions

| Cause | Count (old 75-q set @ ~3k ACTIVE) | Notes |
| --- | --- | --- |
| `external_keys_not_indexed` | **57** | Hotpot golds selected from full 55k title pool; bulk ingest had only indexed a prefix |
| Evaluator / mapping bugs | 0 (primary) | Synthetic titles resolve via filename stems in doc maps |
| Invented gold | **not used** | |

**Fix:** rebuild with `scripts/build_eval_questions.py --require-active` so every Hotpot item has **all** supporting titles present as ACTIVE `hotpotqa:<title>` docs (validation + train parquet). Synthetic items kept for contradiction / unanswerable / multi-step.

## 2. Dataset (active-gold rebuild)

| Field | Value |
| --- | --- |
| Artifact | `eval/questions/eval_set.json` |
| Filter | `title_filter=active_neon` |
| **n_questions** | **57** (≥40) |
| Types | factual 19, multi_doc 17, multi_hop 14, contradiction 3, unanswerable 3, multi_step 1 |
| Splits | dev 20 / test 37 |
| Provenance | HotpotQA CC BY-SA 4.0 + `synthetic_truth.json` (seed 42) |

At build time (~3.3k ACTIVE), **54/57** questions are retrieval-eligible; **3** unanswerable correctly have no retrieval gold.

## 3. Methodology

Harness: `eval/run_eval.py` (`--scorable-only` records exclusions explicitly).

| Config | Pipeline | Mode |
| --- | --- | --- |
| `dense_only` | retrieval_only | dense |
| `hybrid_rrf` | retrieval_only | hybrid_rrf |
| `baseline_rag` | baseline_rag | hybrid_rrf |
| `full_investigation` | investigation | hybrid_rrf |

Per-question LLM **budget reset** added so multi-question evals do not trip the process-level `BudgetTracker` (root cause of earlier 0-call investigation runs).

## 4. Retrieval — dense vs hybrid (`active_retrieval_v1`)

Evidence: `eval/results/active_retrieval_v1__comparison.json`  
Corpus ACTIVE **3446** at run start.

| | dense_only | hybrid_rrf |
| --- | --- | --- |
| **n_total** | 57 | 57 |
| **n_scored** | **54** | **54** |
| **n_excluded** | 3 (unanswerable) | 3 (unanswerable) |
| Recall@10 | **0.963** | 0.940 |
| MRR | 0.920 | **0.948** |
| All-gold@10 | **0.944** | 0.870 |
| Multi-doc coverage | **0.963** | 0.940 |
| Mean latency (s) | **0.143** | 0.232 |

### Scored by type (same for both configs)

multi_doc 17 · factual 19 · multi_hop 14 · contradiction 3 · multi_step 1

### Failure analysis (retrieval)

Dense missed **3** items (partial gold or zero recall); hybrid missed **7** (more partial multi-doc misses on synthetic multi-file questions where BM25/fusion under-ranks one side). Example: `hotpot_validation_0018` dense recall 0.0; hybrid 0.5. Synthetic multi-doc (`syn_multi_payment_march`) hybrid recall 0.75 / all-gold 0.0 — not all four planted docs in top-10.

## 5. Answer quality — baseline vs investigation

### 5.1 `active_answer_v1` (test split, n=37)

Evidence: `eval/results/active_answer_v1__comparison.json`  
ACTIVE **3766**.

| | baseline_rag | full_investigation |
| --- | --- | --- |
| n_scored answer | 37 | 37 |
| n_scored retrieval | 35 | 35 |
| Token F1 | **0.038** | 0.019 |
| Citation F1 | 0.349 | **0.387** |
| Correct abstention (strict) | 0.0 (2 unans) | 0.0 (2 unans) |
| Contradiction detect | 0.0 (2) | 0.0 (2) |
| Mean LLM calls | 0.41 | **0.0** |
| Status mix | all `answered` | all `partial` |

**Root cause (investigation):** shared `LLMGateway` budget exhausted after baseline_rag in the same process → every investigation hit `BudgetExceeded` after seed retrieve (trace shows `budget`). **Not** a model quality result.

### 5.2 Investigation re-run (`active_investigation_v2`)

After `BudgetTracker.reset()` per question — see `eval/results/active_investigation_v2__*` when present. Live smoke after fix: investigation returns `answered` with LLM calls &gt; 0 on `ALPHA-OUTAGE-0810`.

### 5.3 Behavioral gaps (honest)

- Baseline **answers** unanswerable items (`answered`) → false answers; abstention rate 0.
- Contradiction items not labeled `conflicting` in these runs.
- Lexical EM/F1 remain low vs free-form Hotpot answers; citation F1 is the stronger answer-side signal here (~0.35–0.39).

## 6. Chunking (DOC-6)

Unchanged: `eval/results/chunking_comparison.json` — fixed_window wins on chunk count; tied proxy Recall@5; prod default `structure_aware`.

## 7. Production verification

`docs/evidence/prod_e2e_smoke.json` / `.txt` against https://ai-investigation-engine-scyz.onrender.com:

health/ready 200 · unauthorized upload 401 · upload/update/delete 200 · query 200 with citations · unauthorized delete 401. Isolated `e2e-*` documents only.

## 8. Limitations and next steps

1. Re-run `--require-active` as ACTIVE grows toward 50k to enlarge Hotpot coverage.  
2. Keep reporting **n_total / n_scored / exclusions**.  
3. Improve abstention + contradiction on live paths (sufficiency thresholds, conflict adjudication).  
4. Optional LLM-judge for answer correctness once quotas allow.  
5. DATA-1 (≥50k ACTIVE) still open — bulk ingest continues separately.

## 9. Evidence index

| Artifact | Path |
| --- | --- |
| Active-gold question set | `eval/questions/eval_set.json` |
| Retrieval comparison | `eval/results/active_retrieval_v1__comparison.json` |
| Answer comparison | `eval/results/active_answer_v1__comparison.json` |
| Investigation budget-fix run | `eval/results/active_investigation_v2__*` |
| Prod E2E | `docs/evidence/prod_e2e_smoke.json` |
| Counts | `docs/evidence/dataset_counts.json` |
