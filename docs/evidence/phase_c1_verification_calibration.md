# Phase C.1 — Verification Calibration and Candidate Freeze

**Date:** 2026-11-03  
**Scope:** Paired B↔C comparison, rejection audit, STRICT vs SOFT policies, coverage calibration.  
**Not in scope:** Sealed test; production default change.

## 1. Matched Phase B vs C (identical Hotpot IDs)

Artifact: `eval/results/phase_c1_paired_b_vs_c.json`

| Config | n | B token F1 | C token F1 | Δ F1 | B multi-hop | C multi-hop | B→C abstain when B F1≥0.5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | **24** | **0.667** | **0.339** | −0.328 | 0.409 | **0.609** | 9 |
| raw | **22** | **0.587** | **0.264** | −0.323 | 0.444 | 0.450 | 8 |
| legacy | 24 | 0.173 | 0.166 | −0.007 | 0.136 | 0.091 | 0 |

Unmatched Phase C averages previously understated sample differences; the F1 drop is real on the paired set.

## 2. Why F1 declined (rejection audit)

Artifact: `eval/results/phase_c1_rejection_audit.json` (oracle n=9, raw n=8 cases).

Primary categories (oracle):
- `missing_required_hop_or_cite` / incomplete chain
- `quote_mismatch`
- `overly_restrictive_coverage_threshold` (observed coverage ≈0.67 vs threshold 0.85)
- `answer_not_entailed_low_coverage`
- clean model abstention

**Verification mistakes vs model/chain gaps:** roughly 3 vs 5 on oracle. The 0.85 lexical threshold and STRICT clearing of one-hop answers explain a large share of the paired F1 drop—not only “better honesty.”

## 3. STRICT vs SOFT (same raw_model)

Harness: `eval/run_phase_c1.py` — one LLM call, offline dual verify. Coverage threshold calibrated to **0.65**.

### Hotpot paired oracle slice (`phasec1_policy_v1`, n=18 scored before quota stop)

| Policy | full-answer F1 | raw overlap F1 | full_answered | partial | chain_ok | multi-hop | unsupported full |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| STRICT | 0.341 | 0.341 | 0.444 | 0.000 | 0.444 | 0.611 | **0.000** |
| SOFT | 0.341 | **0.535** | 0.444 | **0.222** | 0.444 | 0.611 | **0.000** |

SOFT does **not** raise unsupported full answers. It surfaces quote-supported content as `partial` when a hop is missing, increasing usable coverage without claiming a verified multi-hop conclusion.

### Robustness (`phasec1_robust_v1`, n=10)

Identical STRICT/SOFT: 3/3 contradictions → `conflicting`; revision/timeframe controls answered (no false contradiction); missing evidence/hop/empty abstain; injection still grounded. Independent-numbers control still over-abstains (known residual).

## 4. Calibration changes

- `DEFAULT_COVERAGE_THRESHOLD`: 0.85 → **0.65** (above Phase B 0.60; recovers ~0.67 borderline cases).
- `MultiHopPolicy.STRICT` / `SOFT` in `app/investigation/verify.py`.
- Settings: `READER_MULTI_HOP_POLICY` (default **soft**), `READER_COVERAGE_THRESHOLD` (default **0.65**).
- Experimental flag remains **false** in production.

No free-tier semantic LLM entailment checker added (quota already binding); deterministic coverage + quotes retained.

## 5. Selected freeze: **SOFT**

Priorities applied in order:

1. Unsupported full answers = 0 (both policies).  
2. Multi-hop completeness for full answers unchanged (~0.61).  
3. Supported coverage improves via `partial` under SOFT.  
4. Raw answer overlap F1 improves (0.34 → 0.54) without inventing full EM credit.  
5. Contradiction/abstention behavior matched on synthetic pack.  
6. Same LLM cost as STRICT (verify-only difference).

**Frozen candidate:** see `docs/evidence/phase_c1_candidate_freeze.md`.

## 6. Negative controls (`phasec1_neg_v1`, n=38)

After scoring fix (SOFT `partial` on missing_one_hop = appropriate):

| Policy | false_answer | appropriate abstention/partial | remove/distractor/counterfactual abstain |
| --- | ---: | ---: | ---: |
| STRICT | **0.00** | **1.00** | **1.00** |
| SOFT | **0.00** | **1.00** | **1.00** |

SOFT missing_one_hop: 6 insufficient + 2 partial (honest fragments).

## 7. Remaining blockers before sealed

- Expand Hotpot policy eval beyond n=18 when quota allows (direction already clear).  
- Independent-numbers over-abstention.  
- Sealed 300 still locked; Render default still legacy.
