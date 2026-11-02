# Evaluation Report

**Project:** Applied AI Investigation Engine  
**Updated:** 2026-11-02 (Phase A eval integrity)  
**Corpus:** ACTIVE **55,081** / Qdrant **56,890** (`meets_data1_50k: true`). Ingestion complete; earlier pre-50k runs remain historical only.

## 0. Phase A — evaluation integrity (2026-11-02)

Full write-up: `docs/evidence/phase_a_eval_integrity.md`.

### Scoring correction (predictions unchanged)

M7 adaptive predictions re-scored with citation markers stripped:

| | Legacy (cite tokens in F1) | Corrected | Delta |
| --- | ---: | ---: | ---: |
| token F1 (n=62) | 0.183 | **0.223** | +0.040 |
| exact match | 0.000 | **0.145** | +0.145 |

Artifact: `eval/results/m7_test_adapt_v3__full_investigation__rescored_cite_strip.json`.  
**Do not treat the delta as a model improvement.**

### Retrieval mode alignment (legacy test, k=10, n_scored=60)

Production API default = **`hybrid_rerank`**. Historical answer eval used **`hybrid_rrf`**.

| Mode | R@10 | MRR | all-gold@10 | latency (s) |
| --- | ---: | ---: | ---: | ---: |
| dense_only | 0.908 | 0.914 | 0.833 | 0.105 |
| hybrid_rrf | **0.925** | 0.939 | **0.850** | 0.109 |
| hybrid_rerank | 0.858 | **0.958** | 0.717 | 0.213 |

Reranker helps MRR, hurts set coverage. Production default **unchanged** pending explicit decision.  
Artifact: `eval/results/phase_a_retrieval_v1__comparison.json`.

### Held-out redesign

- Legacy `eval_set.json` (94 / test 62): **contaminated by M6–M7 tuning** — diagnostic only.
- New `eval/questions/heldout_v1.json`: **85** questions (dev 26 / frozen test **59**); Hotpot native bridge/comparison labels; excludes legacy question texts; expanded unanswerable×3 + contradiction×2 (still small-n).

### Evidence retention (diagnostic)

On 8 multi-gold cases, mean gold-doc recall: retrieval/extract **0.81** → after claim filtering **0.56** → citations **0.31**.  
Artifact: `docs/evidence/phase_a_retention.json`.

## 1. Dataset (active-gold rebuild @ full corpus) — legacy

| Field | Value |
| --- | --- |
| Artifact | `eval/questions/eval_set.json` (**legacy / diagnostic**) |
| Filter | `title_filter=active_neon` (55,081 ACTIVE Hotpot titles) |
| **n_questions** | **94** (≥40) |
| Types | factual 78, multi_doc 4, multi_hop 5, contradiction 3, unanswerable 3, multi_step 1 |
| Splits | dev 32 / test 62 |
| Label caveat | Many Hotpot items labeled `factual` via short answer length; native Hotpot `type` ignored (fixed in heldout_v1) |

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
| Render Milestone 3 @ `428ed09` / `fecabea` | Airport **~67–75s** (was ~142s); contradiction + unanswerable **PASS**; colony **insufficient @ ~48s** (was timeout); multi-doc honest `llm_unavailable` with `groq:daily_quota`; multihop answer quality still weak. Per-stage traces show retrieval then LLM as dominant costs. | `docs/evidence/prod_smoke_suite.json` |
| Local Milestone 4 multi-hop | OSU/CSUDH **answered** with both gold titles cited (~5–9s); Lent→Ice Road Truckers premiere date **answered**; Robinson→Perdita/Sicilia **answered**; colony abstention + airport factual preserved. Failure mode before fix was claim anaphora + synthesis hedge, not missing Qdrant recall. | local investigation probes |
| Render Milestone 4 @ `8964e79` | Smoke **7/7 PASS**: airport ~14s; OSU/CSUDH ~14s (2 gold cites); Lent premiere ~22s; Robinson/Sicilia ~11s; colony abstain; contradiction answered; unanswerable abstain. | `docs/evidence/prod_smoke_suite.json` |
| Answer eval Milestone 5 `m5_answer_v1/v2` | Test split **62** questions on ACTIVE 55,081. Investigation: mean LLM calls **0.0**, mean latency **~0.44–0.82s**, abstention **0.5**, contradiction detection **0.5**. Baseline: always `answered` (abstention **0.0**, contradiction **0.0**), higher citation F1 from unrestricted snippet dumps. 1 Qdrant timeout in v2. | `eval/results/m5_answer_v2__*` |
| Render Milestone 5 @ `283bfc3` | Smoke **7/7 PASS**, **0 LLM calls**/case: airport ~11s; three multi-hops ~9–11s; colony/unanswerable abstain ~3–4s; contradiction **`conflicting`** ~3s with 08:10 vs 14:00. | `docs/evidence/prod_smoke_suite.json` |
| Answer eval Milestone 6 (`m6_test_*`) | Same test **62** / ACTIVE 55,081. Deterministic token F1 **0.080**; adaptive **0.153** (23 LLM / 39 det); abstention **1.0**; answered-only cite F1 **0.519**. Baseline F1 0.092, abstention 0.0. M5 baseline preserved. | `eval/results/m6_test_adapt_v1__*`, `docs/evidence/m6_report.md` |
| Render Milestone 6 @ `a748661` | Smoke **10/10 PASS** (7 curated demos + multi-doc + budget isolation). LLM path live on multi-doc/budget cases; curated multi-hops stay **0 LLM** short spans. | `docs/evidence/prod_smoke_suite.json` |
| Answer eval Milestone 7 (`m7_test_adapt_v3`) | Same test **62** / ACTIVE 55,081. Token F1 **0.183** legacy / **0.223** cite-stripped re-score; cite F1 **0.365**; abstention **1.0**; contradiction **1.0**. Retrieval mode was `hybrid_rrf` (not prod `hybrid_rerank`). | `eval/results/m7_test_adapt_v3__*`, rescored cite-strip JSON, `docs/evidence/m7_report.md` |
| Render Milestone 7 @ `611b0d4` | Smoke **10/10 PASS**. Unseen: JWT span, causal conflict, Genesee LLM multi-hop, Hush LLM birth-date, approver abstain. | `docs/evidence/prod_smoke_suite.json` |
| Phase A eval integrity | Scoring + citation parser fixes; retrieval mode comparison; retention probe; heldout_v1. | `docs/evidence/phase_a_eval_integrity.md` |

## 5. Quality fixes reflected in metrics intent

- Per-request `BudgetTracker.reset()`; budget death → `llm_unavailable` (not fake `partial` claim dumps)
- Question-conditioned sufficiency → missing-entity questions abstain
- Citation pruning to answer labels; relative retrieval floor; phrase-aware rerank
- `/api/version` exposes `git_commit`
- Multi-hop: entity seeding, title fidelity, bridge hops, anaphoric claims, grounded second-hop filtering
- Milestone 5: deterministic plan/synthesis + seed/bridge short-circuit; temporal deploy-time conflict detection; trace `synthesis_mode`
- Milestone 6: short span extraction; adaptive LLM when span confidence &lt; 0.7; question-gated temporal conflicts; approver redaction abstention; answered-only citation diagnostic

## 6. Remaining gaps

1. Cite-stripped EM is 0.145 on legacy M7 predictions; Hotpot alias/format gaps remain.
2. Free-tier quotas still constrain large adaptive runs.
3. Legacy test set is tuning-contaminated; final claims must use `heldout_v1` (not yet answer-evaluated).
4. Claim filtering / citation prune lose gold docs after retrieval (Phase B reader candidate).
5. Unanswerable/contradiction counts remain small even after heldout expansion.

## 7. Evidence index

| Artifact | Path |
| --- | --- |
| Counts | `docs/evidence/dataset_counts.json` |
| Retrieval @55k | `eval/results/full55k_retrieval_v1__*` |
| Answer subset | `eval/results/full55k_answer_v1__*` |
| Prod probe | `docs/evidence/prod_quality_probe.json` |
| Local RAG probe | `docs/evidence/local_rag_quality_probe.json` |
| Colony abstention | `docs/evidence/colony_abstention_scripted.json` |
| M5 answer eval | `eval/results/m5_answer_v2__*` |
| M6 audit + report | `docs/evidence/m6_eval_audit.md`, `docs/evidence/m6_report.md` |
| M6 answer eval | `eval/results/m6_test_det_v1__*`, `eval/results/m6_test_adapt_v1__*` |
| Reviewer demos | `docs/evidence/reviewer_demo_cases.md` |
| Phase A integrity | `docs/evidence/phase_a_eval_integrity.md` |
| Phase A retention | `docs/evidence/phase_a_retention.json` |
| Phase A retrieval | `eval/results/phase_a_retrieval_v1__*` |
| M7 cite-strip rescore | `eval/results/m7_test_adapt_v3__full_investigation__rescored_cite_strip.json` |
| Held-out v1 | `eval/questions/heldout_v1.json` |
