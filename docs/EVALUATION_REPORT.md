# Evaluation Report

**Project:** Applied AI Investigation Engine  
**Updated:** 2026-10-30  
**Corpus:** ACTIVE **55,081** / Qdrant **56,890** (`meets_data1_50k: true`). Earlier pre-50k runs remain historical.

## 1. Dataset (active-gold rebuild @ full corpus)

| Field | Value |
| --- | --- |
| Artifact | `eval/questions/eval_set.json` |
| Filter | `title_filter=active_neon` (55,081 ACTIVE Hotpot titles) |
| **n_questions** | **94** (≥40) |
| Types | factual 78, multi_doc 4, multi_hop 5, contradiction 3, unanswerable 3, multi_step 1 |
| Splits | dev 32 / test 62 |

## 2. Full-corpus retrieval (`full55k_retrieval_v1`)

Evidence: `eval/results/full55k_retrieval_v1__comparison.json`  
ACTIVE **55081**. Scorable retrieval gold: **n_scored=91** (3 unanswerable excluded).

| | dense_only | hybrid_rrf |
| --- | --- | --- |
| n_total | 94 | 94 |
| n_scored | **91** | **91** |
| Recall@10 | **0.890** | 0.887 |
| MRR | 0.904 | **0.919** |
| All-gold@10 | **0.802** | 0.769 |
| Mean latency (s) | **0.350** | 1.155 |

Dense still edges set-coverage metrics; hybrid still edges MRR (first relevant rank).

## 3. Answer quality (`full55k_answer_v1`, controlled)

Evidence: `eval/results/full55k_answer_v1__*`  
Limit **12** test questions; `--pause-s 2 --stop-after-llm-unavailable 3`.

| | baseline_rag | full_investigation |
| --- | --- | --- |
| n_total | 12 | 12 |
| n_scored answer | **12** | **5** (then provider stop) |
| Token F1 | 0.115 | 0.092 |
| Citation F1 | **0.633** | 0.333 |
| Status | 12× `answered` | 2× `answered`, 3× `llm_unavailable`, 7× skipped |
| Mean LLM calls | 1.0 | 5.0 (on scored) |

**Honest limits:** Investigation stopped after Groq/Gemini failures (TPM 413 / parse 400). Baseline still answers unanswerable items (abstention rate 0.0). Do not treat this subset as full test-split quality.

## 4. Production / local quality probes (post-fix)

| Probe | Result | Evidence |
| --- | --- | --- |
| Colony abstention (scripted LLM + live index) | **`insufficient`**, 0 claims/cites | `docs/evidence/colony_abstention_scripted.json` |
| Local live LLM | Colony `llm_unavailable` (provider TPM); Airport **`answered`** with **1** citation (Woodrum Field / ~6 km NW of Roanoke) | `docs/evidence/local_rag_quality_probe.json` |
| Render public @ `0036003` (pre-300s budget) | All four cases returned explicit **`llm_unavailable`** with evidence preview after **120s wall-clock** on Free tier (no fake partial essays). | `docs/evidence/prod_quality_probe.json` |
| Render public @ `0f6adc3` / `c03b155` | Deploy SHA + ACTIVE **55,081** confirmed. Behavioral smoke: airport **PASS** (~142s, 1 cite); budget isolation **PASS**; multi-doc/multi-hop/unanswerable hit provider limits or client timeouts; colony/contradiction returned honest `llm_unavailable`. | `docs/evidence/prod_smoke_suite.json` |

## 5. Quality fixes reflected in metrics intent

- Per-request `BudgetTracker.reset()`; budget death → `llm_unavailable` (not fake `partial` claim dumps)
- Question-conditioned sufficiency → missing-entity questions abstain
- Citation pruning to answer labels; relative retrieval floor; phrase-aware rerank
- `/api/version` exposes `git_commit`

## 6. Remaining gaps

1. Live contradiction/abstention rates under provider success still thin on measured subsets.
2. Full investigation answer eval needs a quota-healthy window (no early stop).
3. Render Free latency can still trip budgets or provider TPM; degraded mode must stay honest.

## 7. Evidence index

| Artifact | Path |
| --- | --- |
| Counts | `docs/evidence/dataset_counts.json` |
| Retrieval @55k | `eval/results/full55k_retrieval_v1__*` |
| Answer subset | `eval/results/full55k_answer_v1__*` |
| Prod probe | `docs/evidence/prod_quality_probe.json` |
| Local RAG probe | `docs/evidence/local_rag_quality_probe.json` |
| Colony abstention | `docs/evidence/colony_abstention_scripted.json` |
