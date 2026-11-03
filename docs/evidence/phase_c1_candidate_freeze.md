# Phase C.1 frozen candidate

**Status:** Frozen for a **future** sealed unlock — sealed test **not** run in this phase.  
**Date:** 2026-11-03  
**Production default:** `EXPERIMENTAL_PASSAGE_READER=false` (unchanged)

## Selected policy: SOFT

| Knob | Frozen value |
| --- | --- |
| Multi-hop policy | `soft` (`READER_MULTI_HOP_POLICY=soft`) |
| Coverage threshold | `0.65` (`READER_COVERAGE_THRESHOLD=0.65`) |
| Prompt | `reader_v2_phase_c` |
| Verify module | `app/investigation/verify.py` (`verify_c1_v1`) |
| Reader | `structured_reader_v2` |
| Eval retrieval (experiments) | `hybrid_rrf`, k=10 |
| Prod retrieval default | `hybrid_rerank` |
| Benchmark sealed | `phase_b_bench_v1_test_sealed.json` (untouched) |

### SOFT semantics

- Full `answered` requires verified quotes **and** complete evidence chain.
- If the answer is quote-supported but the chain is incomplete → `partial` with only supported content + `missing_info` / `next_query`.
- Never treats a partial chain as a verified multi-hop conclusion (`evidence_chain_ok=false`).
- Exact quote-in-source and label checks remain mandatory.

## Rationale (priority order)

1. Unsupported full-answer rate = **0** (STRICT and SOFT).  
2. Multi-hop completeness for full answers preserved (~0.61 on paired oracle slice).  
3. SOFT improves supported coverage via honest `partial` (partial rate ~0.22 Hotpot / ~0.05 on missing-hop controls).  
4. Paired raw overlap F1 rises under SOFT without granting full-answer EM/F1 for incomplete chains.  
5. Robustness: contradiction recall 3/3; false-contradiction 0 on revision/timeframe controls; remove/distractor/counterfactual abstention 1.0.  
6. No extra LLM cost vs STRICT.

## Acceptance criteria (pre-registered for sealed unlock)

1. Unsupported full-answer rate ≤ 0.02 on locked dev Hotpot.  
2. False-answer rate on remove_gold + distractors + counterfactual ≤ 0.05.  
3. Appropriate status on missing_one_hop (insufficient **or** partial under SOFT) ≥ 0.95.  
4. Multi-hop all-gold cited ≥ 0.50 on oracle items with both golds present and status=`answered`.  
5. Contradiction recall ≥ 0.80 on `phase_c_robustness_v1` true contradictions; false-contradiction ≤ 0.20 on non-conflict controls.  
6. Feature flag remains false on Render until canary.

## Rollback

Set `EXPERIMENTAL_PASSAGE_READER=false` (already default). Legacy `_finalize` unchanged. No corpus/index rollback needed.

## Do not change after sealed unlock

Code SHA, prompt text, SOFT policy, 0.65 threshold, retrieval mode for the sealed run, and model IDs recorded in the sealed result JSON.
