# Phase C — Reader Grounding, Multi-Hop Completeness, Controlled Validation

**Date:** 2026-11-03  
**Scope:** Diagnose Phase B shuffle control; harden verification; negative controls; contradiction robustness; matched A/B on **development** only.  
**Not in scope:** Sealed 300-test unlock; production default change; corpus reindex.

## 1. Shuffle-control root cause (Phase B failure)

**What was shuffled:** Only the *text bodies* of gold paragraphs were permuted among gold passage objects. Titles and labels stayed attached to the original objects.

**What was NOT removed:** All gold supporting content remained in the prompt. With typical Hotpot 2-paragraph gold, shuffle is a title↔text remapping, not an evidence ablation.

**Cache:** `e0_oracle_shuffle` did **not** reuse `e0_oracle` cache (`cache_hit=False`). Cache leakage was not the cause.

**Scoring:** Answer F1 could stay high because supporting strings were still present; quote token-overlap “support” still passed.

**Evidence:** `scripts/diagnose_shuffle_control.py` — among 40 paired Hotpot items, **24 identical answers**, **22 with both F1≥0.5**.

**Fix:** Replaced weak shuffle with rigorous controls (remove gold, distractors, counterfactual, missing hop, title swap) and evidence-dependent scoring that does not credit unsupported answers.

## 2. Verification hardening

Module: `app/investigation/verify.py` (used by `reader.py`).

| Check | Behavior |
| --- | --- |
| Label existence | Reject fabricated labels |
| Exact quote in passage | Deterministic substring (whitespace-normalized) |
| Answer entailment | Prefer answer substring in quotes; else ≥0.85 content-token coverage (stricter than Phase B 0.6) |
| Multi-hop chain | Optional `require_multi_hop`: need ≥`min_hops` distinct verified labels |
| Contradiction | Model `conflict_kind` + conservative year-conflict heuristic |
| Unsupported answers | Downgraded to abstention / conflicting |

Prompt `reader_v2_phase_c` requires hop roles and explicit conflict_kind.

Production flag remains `EXPERIMENTAL_PASSAGE_READER=false`. Multi-hop requirement defaults **off** in production path; eval enables it when ≥2 gold titles are in context.

## 3. Negative controls (dev pilot `phasec_neg_pilot`, n=8×5=40)

| Control | correct abstention | false answer | notes |
| --- | ---: | ---: | --- |
| remove_gold | **1.00** | **0.00** | Empty context |
| distractors | **1.00** | **0.00** | Unrelated passages |
| counterfactual | **1.00** | **0.00** | No pretrained Hotpot answers |
| missing_one_hop (before) | 0.625 | 0.375 | Single-hop answers slipped |
| missing_one_hop (`phasec_neg_v2`, mh forced) | **1.00** (n=4 scored before quota) | **0.00** | Incomplete chain rejected |
| swap_titles | n/a | n/a | Gold text retained; F1 ~0.5–0.66 expected |

Cache keys now include `verify_id` + `require_multi_hop` (prevents stale verify reuse).  
Overall: remove/distractor/counterfactual abstention = **1.00**; false-answer on those = **0.00**.

## 4. Robustness set

`phase_c_robustness_v1` — **10** synthetic items (true contradictions ×3, revision/timeframe/independent-number controls, missing evidence/hop, empty context, injection). Sealed Hotpot untouched.

**Reader (c_raw) on robustness:** 3/3 true contradictions → `conflicting`; revision/timeframe controls answered without false contradiction; missing evidence abstains; injection still yields correct grounded answer.

**Legacy:** false-answers empty context; false-contradicts revision control; weak contradiction labeling.

## 5. Matched A/B (`phasec_ab_v1`, limit 24 Hotpot + 10 robustness)

Paired Hotpot n=22 (provider failures excluded from pair):

| Config | token F1 | EM | answer_supported | multi-hop all-gold cited |
| --- | ---: | ---: | ---: | ---: |
| Phase B oracle (ref, n=40) | 0.645 | 0.525 | 0.725 | 0.333 |
| Phase B raw (ref) | 0.530 | 0.425 | 0.675 | 0.294 |
| Phase B legacy (ref) | 0.116 | 0.025 | 0.700* | 0.088 |
| **C oracle (hardened)** | 0.324 | 0.227 | 0.409 | **0.619** |
| **C raw (hardened)** | 0.264 | 0.182 | 0.318 | **0.450** |
| **C legacy** | 0.181 | 0.045 | 0.818* | 0.095 |

\*Legacy “supported” = status answered (not quote-verified).

**Interpretation:** Hardened multi-hop chain checks roughly **double** all-gold citation completeness vs Phase B, at the cost of lower EM/F1 (incomplete chains abstain instead of one-hop answers). Evidence-dependence and contradiction behavior improve vs legacy.

## 6. Cost / quota

- Reader: 1 call/q; oracle ~820 tok; raw ~1.6k tok; p50 ~0.8–1.1s.
- Groq daily_quota / Gemini rate limits caused a few oracle/raw failures (reported separately).
- No paid infra; prod default unchanged.

## 7. Frozen candidate?

**Not yet for sealed unlock.** Reasons:

1. Hardened reader trades F1 for faithfulness; need a locked policy (strict chain vs soft `partial`) before one-shot sealed eval.
2. Development n≈22–40 with quota interruptions — uncertainty remains.
3. `missing_one_hop` still needed a post-hoc require_multi_hop force (re-run `phasec_neg_mhfix`).
4. Feature flag must stay false on Render until sealed + canary.

**If proceeding later:** freeze SHA, `prompt_id=reader_v2_phase_c`, retrieval `hybrid_rrf` k=10 for eval / prod still `hybrid_rerank`, record acceptance: evidence-dependent F1 ≥ legacy by clear margin, false-answer on remove/distractor/counterfactual ≤0.05, multi-hop ≥0.50, contradiction recall ≥0.8 on synthetic pack.

## 8. Artifacts

- Diagnosis: `scripts/diagnose_shuffle_control.py`
- Verify: `app/investigation/verify.py`
- Controls: `eval/negative_controls.py`, `eval/run_phase_c.py`
- Results: `eval/results/phasec_neg_pilot__*`, `eval/results/phasec_ab_v1__*`
- Robustness: `eval/questions/phase_c_robustness_v1.json`
