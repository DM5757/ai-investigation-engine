# Evaluation Report

**Project:** Applied AI Investigation Engine  
**Date:** 2026-10-29  
**Corpus note:** Preliminary while ACTIVE &lt; 50k (measured ~35.7k ACTIVE at 2026-10-29 17:23 Asia/Tbilisi; ingest still running). Metrics use **transparent denominators**. Retrieval/answer eval artifacts below were measured earlier the same day on a smaller ACTIVE corpus — do not reinterpret them as full-corpus scores.

## 1. Why earlier runs scored only ~7 questions

| Cause | Count (old 75-q set @ ~3k ACTIVE) | Notes |
| --- | --- | --- |
| `external_keys_not_indexed` | **57** | Hotpot golds selected from full 55k title pool; bulk ingest had only indexed a prefix |
| Evaluator / mapping bugs | 0 (primary) | Synthetic titles resolve via filename stems in doc maps |
| Invented gold | **not used** | |

**Fix:** rebuild with `scripts/build_eval_questions.py --require-active` so every Hotpot item has **all** supporting titles present as ACTIVE `hotpotqa:<title>` docs. Synthetic items kept for contradiction / unanswerable / multi-step.

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

**Do not claim that all 75 original questions were fully scored.** The original 75-q set is historical; active evaluation uses the 57-q rebuild above.

## 3. Methodology

Harness: `eval/run_eval.py` (`--scorable-only` records exclusions explicitly).

| Config | Pipeline | Mode |
| --- | --- | --- |
| `dense_only` | retrieval_only | dense |
| `hybrid_rrf` | retrieval_only | hybrid_rrf |
| `baseline_rag` | baseline_rag | hybrid_rrf |
| `full_investigation` | investigation | hybrid_rrf |

Per-question LLM **budget reset** so multi-question evals do not trip the process-level `BudgetTracker`.  
Eval also supports `--pause-s` and `--stop-after-llm-unavailable` to avoid hammering free-tier providers after repeated 429s.

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

### Why dense wins Recall@10 / All-gold@10 while hybrid wins MRR

- **Recall@10 / All-gold@10 (dense higher):** several multi-doc / synthetic items need *all* gold docs in the top-10. Sparse BM25 + RRF can demote one supporting doc just outside k=10 even when another gold ranks first — lowering set coverage and all-gold hit rate.
- **MRR (hybrid higher):** when hybrid *does* surface a gold doc, it more often ranks the first relevant doc at position 1 (lexical exact-title / keyword boost), improving reciprocal rank even if the full gold set is incomplete.
- This is a ranking/fusion tradeoff on a partial corpus, not proof that hybrid is “worse overall.”

### Failure analysis (retrieval)

Dense missed **3** items; hybrid missed **7** (more partial multi-doc misses). Example: `syn_multi_payment_march` hybrid recall 0.75 / all-gold 0.0.

## 5. Answer quality — baseline vs investigation

### 5.1 `active_answer_v1` (test split, n=37) — budget bug (invalid investigation)

Evidence: `eval/results/active_answer_v1__comparison.json`  
ACTIVE **3766**.

| | baseline_rag | full_investigation |
| --- | --- | --- |
| n_scored answer | 37 | 37 |
| Token F1 | **0.038** | 0.019 |
| Citation F1 | 0.349 | **0.387** |
| Mean LLM calls | 0.41 | **0.0** |
| Status mix | all `answered` | all `partial` |

**Root cause:** shared `BudgetTracker` exhausted after baseline → investigation never called the LLM. **Not** a model quality result.

### 5.2 `active_investigation_v2` (budget fix; provider-limited)

Evidence: `eval/results/active_investigation_v2__*`  
Test split **n_total=37**. After budget reset, investigation calls the LLM, but **Groq free-tier tokens/day (200k TPD)** exhausted mid-run. Gemini fallback also hit rate limits / tool round-trip issues (later mitigated by preserving Gemini `thought_signature`).

| Status | Count |
| --- | --- |
| `answered` | 6 |
| `partial` | 3 |
| `llm_unavailable` | **27** |
| other / error | 1 |

**Provider-available subset (status ≠ llm_unavailable): n=9**  
Among those 9: citation signal is present; lexical EM/F1 remain low vs free-form Hotpot answers.  
**Contradiction detection rate on scored contradiction items: 0.0**  
**Correct abstention (strict) on unanswerable: 0.0**

Skipped due to provider limits must be counted explicitly — they are **not** quality failures of the retrieval stack.

### 5.3 Baseline under same corpus/questions

`active_answer_v1` baseline_rag on the same test split: **37/37 `answered`**, including unanswerable items (false answers). Citation F1 ≈ 0.35. Investigation’s advantage when the LLM is available is citation grounding + degraded evidence preview under failure; it does **not** yet beat baseline on strict abstention/contradiction rates in measured live samples.

## 6. Contradiction and abstention

| Probe | Result | Evidence |
| --- | --- | --- |
| Deterministic claim gates | **PASS** (agree→0 conflicts; disagree→conflict; empty→insufficient) | `docs/evidence/behavioral_rag_smoke.json` |
| Unit/scripted tests | **PASS** | `tests/unit/test_contradictions.py`, `test_sufficiency.py`, scripted investigation |
| Live Gemini investigation (after thought_signature fix) | Runs end-to-end (`answered`, citations&gt;0, llm_calls≥2) but **did not** emit `conflicting` / `insufficient` on planted synthetic items | same evidence file (`gemini_only_after_signature_fix`) |
| Prod abstention probe | HTTP 200; status `partial` under LLM degradation (Groq TPD exhausted) | `docs/evidence/prod_e2e_smoke.json` |

**Honest gap:** pipeline claim extraction / sufficiency thresholds do not yet convert planted synthetic conflicts into `conflicting` / `insufficient` statuses on the live path. Deterministic gates work; live status labeling remains a known defect vs assignment RAG-5/RAG-6 intent.

## 7. Chunking (DOC-6)

Unchanged: `eval/results/chunking_comparison.json` — fixed_window wins on chunk count; tied proxy Recall@5; prod default `structure_aware`.

## 8. Production verification

`docs/evidence/prod_e2e_smoke.json` against https://ai-investigation-engine-scyz.onrender.com (2026-10-29 continuation):

health/ready 200 · unauthorized upload 401 · upload/update/delete 200 · query 200 (citations; **degraded=true** while Groq TPD exhausted) · abstention probe 200 · unauthorized delete 401. Isolated `e2e-*` documents only.

Public UI (`/`) returns 200 with Ask/Documents/Evaluation tabs.

**Deployed git commit:** Render does not expose SHA via `/api/version` (reports app `0.1.0`). Local/GitHub `main` after this push should be the submission-ready commit recorded in `docs/PROGRESS.md`. Confirm Render dashboard shows that commit after auto-deploy.

## 9. Limitations and next steps

1. DATA-1 (≥50k ACTIVE) still open — bulk ingest continues (`batch_size=16`, Qdrant upsert retries). Trust `docs/evidence/dataset_counts.json`.
2. Re-run `--require-active` and full answer eval after Groq TPD resets / ACTIVE grows.
3. Improve live contradiction/abstention: stronger claim extraction from planted synthetic pairs; stricter sufficiency when no verified claims match the question entity.
4. Keep reporting **n_total / n_scored / exclusions / provider skips**.

## 10. Evidence index

| Artifact | Path |
| --- | --- |
| Active-gold question set | `eval/questions/eval_set.json` |
| Retrieval comparison | `eval/results/active_retrieval_v1__comparison.json` |
| Answer comparison (budget-bug investigation) | `eval/results/active_answer_v1__comparison.json` |
| Investigation after budget fix (partial) | `eval/results/active_investigation_v2__*` |
| Behavioral contradiction/abstention | `docs/evidence/behavioral_rag_smoke.json` |
| Prod E2E | `docs/evidence/prod_e2e_smoke.json` |
| Counts | `docs/evidence/dataset_counts.json` |
