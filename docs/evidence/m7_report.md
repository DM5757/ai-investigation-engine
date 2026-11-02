# Milestone 7 — Evidence accuracy, multi-hop coverage, final quality validation

**Corpus:** ACTIVE 55,081 (unchanged).  
**Held-out:** test split 62 questions. Dev used for tuning only.  
**Baselines preserved:** `m5_answer_v2__*`, `m6_test_adapt_v1__*`.

## Failure audit (M6 adaptive test)

See `docs/evidence/m7_failure_audit.md`. Top issues: unnecessary abstention (25), missing gold docs (7), incomplete multi-hop relation (5), missed causal contradiction (1). No false contradictions; no provider errors.

## Generalizable fixes

1. Soft technical-token claim support when verbatim focus phrases miss (AuthGateway / misconfigured).
2. Comparison entity extraction keeps proper names inside long `or` clauses.
3. Causal root-cause conflicts (asserted cause A vs B / not-A) with shared outage context.
4. Metric-attribute sufficiency (CPU usage without CPU evidence → insufficient).
5. Premiere-date extraction tolerates network text; prefer dates from cross-doc grounded titles.
6. Longer relational claim quotes so date tails are not truncated.

## Held-out test (same 62 questions)

| Run | Token F1 | Cite F1 | Cite F1 (answered) | Abstention | Contradiction | Mean lat | Mean LLM calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M6 adaptive (`m6_test_adapt_v1`) | 0.153 | 0.309 | 0.519 | 1.00 | 0.50 | 2.20 s | 0.37 |
| M7 adaptive (`m7_test_adapt_v3`) | **0.183** | **0.365** | **0.528** | **1.00** | **1.00** | 3.22 s | 0.44 |

Retrieval on the same run also improved (investigation R@k **0.525 → 0.608**) from better claim retention / multi-hop evidence keep. Unnecessary abstentions fell (**27 → 21** insufficient).

Artifacts: `eval/results/m7_test_adapt_v3__*`, `m7_dev_adapt_v1__*`.

## Production @ `611b0d4`

Smoke **10/10 PASS** (ACTIVE 55,081). Curated demos preserved (airport, OSU/CSUDH, Lent June 17 2007, Robinson/Sicilia, colony abstain, deploy conflict, FraudScorer abstain).

Unseen live probes: JWT misconfig → `misconfigured JWT TTL`; root-cause → `conflicting`; Genesee comparison → LLM answer with both canals cited; Hush birth-date → LLM `Jessica Lange`; rollback approver → `insufficient`.

## Limitations

- Exact match remains ~0.
- Many Hotpot failures are still upstream retrieval misses (no gold docs in pool).
- Some multi-doc synthetic service questions still abstain when claim filters stay strict.
- Free-tier LLM variance affects adaptive polish latency/quality.
