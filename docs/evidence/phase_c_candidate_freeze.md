# Phase C candidate freeze record

**Status:** **NOT unlocked for sealed evaluation**  
**Date:** 2026-11-03  
**Prod default:** `EXPERIMENTAL_PASSAGE_READER=false` (unchanged)

## Implementation pin (when this note was written)

- Prompt: `reader_v2_phase_c` (`app/llm/prompts/reader.py`)
- Verify: `app/investigation/verify.py`
- Reader: `app/investigation/reader.py` mode `structured_reader_v2`
- Eval retrieval: `hybrid_rrf`, k=10
- Production retrieval default: `hybrid_rerank` (unchanged)
- Benchmark sealed: `phase_b_bench_v1_test_sealed.json` — **untouched**

## Acceptance criteria (pre-registered for a future sealed unlock)

1. Evidence-dependent Hotpot F1 on locked dev slice ≥ legacy by ≥0.15 absolute.
2. False-answer rate on remove_gold + distractors + counterfactual ≤ 0.05.
3. Multi-hop all-gold cited ≥ 0.50 on oracle/raw where both golds are in context.
4. Contradiction recall ≥ 0.80 on `phase_c_robustness_v1` true-contradiction items; false-contradiction on non-conflict controls ≤ 0.20.
5. Provider failure rate documented; no silent drops.
6. Feature flag remains false on Render until canary.

## Rollback

Disable flag; legacy `_finalize` path remains. No corpus/index changes to roll back.

## Why sealed is blocked now

Hardened chain checks improved faithfulness/multi-hop but reduced answer F1 vs Phase B. Policy (strict abstain vs soft partial) must be frozen after one more focused dev pass before the single sealed run.
