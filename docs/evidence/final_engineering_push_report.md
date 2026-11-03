# Final engineering push — comprehensive report

**Date:** 2026-11-03  
**Objective:** Strongest verifiably performing evidence-grounded investigation path without demo heuristics; preserve 55k corpus and `submission-2026-10-29`.

## 1. Architecture changes and reasoning

| Change | Why |
| --- | --- |
| Iterative bridge retrieval (`READER_MAX_BRIDGE_ROUNDS=1`) | SOFT `next_query` was previously discarded; one extra search+read recovers missing hops without unbounded loops. |
| Paraphrase / cited-passage support (`verify_final_v1`) | Token coverage on quotes alone rejected valid short answers whose supporting span did not literally repeat the answer string. Secondary check uses **cited** passage bodies only, and only when ≥1 quote already verified. |
| Answer variants (initials / parentheticals) | Cheap deterministic paraphrase without an LLM entailment call. |
| Reader-path preferred mode `hybrid_rrf` | Phase A + Hotpot A/B: equal or better all-gold@K than rerank at lower latency; legacy API default `hybrid_rerank` unchanged when flag is off. |
| Sealed harness `eval/run_sealed_final.py` | One-shot unlock with freeze-manifest SHA binding; separate sealed cache. |

Production default remains **legacy** finalize (`EXPERIMENTAL_PASSAGE_READER=false`).

## 2. Root causes addressed

1. **Heuristic claim filtering** still the main quality cliff vs passage reading (Phase B); reader path retained and hardened.
2. **Verification over-abstention** on paraphrases — mitigated via passage-level support + 0.65 coverage (C.1) + variants.
3. **Dropped bridge queries** — engine now executes selective second retrieval.
4. **Retrieval mode mismatch** — reader experiments and preferred reader API mode align on `hybrid_rrf`.
5. **Unsupported full answers** — still blocked (rate 0.0 on final_dev soft configs).

Not solved in this push: raw-retrieval multi-hop completeness (0.40 all-gold cited on answered raw items) remains below oracle (0.68); needs more reliable hop-2 retrieval, not sealed tuning.

## 3. Matched development results

Artifacts: `eval/results/final_dev_v1__*.json`, `final_retr_ab_v1.json`.

**Retrieval (n=40 Hotpot, no LLM):**

| Mode | Recall@10 | All-gold@10 | MRR | p95 latency |
| --- | --- | --- | --- | --- |
| dense_only | 0.850 | 0.725 | 0.929 | 0.126s |
| hybrid_rrf | **0.912** | **0.825** | 0.921 | 0.171s |
| hybrid_rerank | **0.912** | **0.825** | 0.933 | 0.198s |

**Selected:** `hybrid_rrf`.

**Answer configs (n≈27–30 scored; some Gemini RPM skips):**

| Config | EM | Full F1 | Raw F1 | Supported | Unsupported full | Multi-hop | p50 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| oracle SOFT | 0.259 | 0.357 | 0.505 | 0.630 | 0.0 | 0.684 | 0.87s |
| raw SOFT | 0.222 | 0.259 | 0.419 | 0.481 | 0.0 | 0.400 | 1.08s |
| legacy | 0.0 | 0.0 | 0.156 | 0.233 | 0.233 | 0.0 | 1.55s |

Legacy row includes 9/30 `llm_unavailable` under quota pressure — treat as degraded comparison, not a clean F1 claim.

## 4. Sealed-test results

**Not run.** Groq daily quota exhausted and Gemini RPM saturated during development experiments. Starting a partial sealed run would consume the single unlock without a complete measurement. Harness is ready: `eval/run_sealed_final.py --confirm-sealed-unlock YES`.

## 5–6. Correctness, citations, multi-hop, abstention, contradiction

On `final_raw_soft` / `final_oracle_soft` (dev + robustness):

- Unsupported full-answer rate: **0.0**
- Citation F1 (oracle / raw): **0.895 / 0.789**
- Multi-hop all-gold (oracle answered): **0.684** (meets ≥0.50 gate)
- Correct abstention / contradiction recall / false contradiction: **1.0 / 1.0 / 0.0**
- Partial rate (honest incomplete chains): **0.15–0.19**

## 7. Negative controls

Prior Phase C.1 neg suite (`phasec1_neg_v1`) under SOFT: false-answer and remove/distractor/counterfactual abstention held; missing-hop allows `partial`. Final-push live neg expansion was skipped under quota; robustness subset in `final_dev_v1` reproduced abstention/contradiction gates.

## 8. LLM quotas, tokens, latency

- Groq: `daily_quota` during final_dev.
- Gemini: intermittent `rate_limit_rpm`; failover used after Groq death.
- Mean tokens (raw SOFT): ~1507/call; p50 latency ~1.1s for reader path.
- Persistent caches: `data/cache/final_reader/` (includes `question_id`); sealed cache path reserved separately.

## 9. Live production behavior

- Flag: **`EXPERIMENTAL_PASSAGE_READER` default false** — no promotion without sealed + canary.
- Corpus: **55,081 ACTIVE** (unchanged).
- Rollback: flag off / prior deploy; no index rewrite.

## 10. Test / CI / commits

- Unit: passage reader, bridge retrieval, experimental flag (local pytest via `uv run python -m pytest`).
- Freeze doc: `docs/evidence/final_candidate_freeze.md`.
- Tag `submission-2026-10-29` preserved.

## 11. Deployed SHA and feature-flag state

Promotion **deferred**. Expected prod flag state after this push: **false**. Confirm `/api/version` after any deploy; do not enable reader until sealed unlock succeeds.

## 12. Remaining limitations

1. Sealed evaluation still required before production enablement.
2. Raw multi-hop citation completeness lags oracle; bridge helps only when the model emits a useful `next_query`.
3. Free-tier LLM quotas truncate matched evals; figures above disclose skips.
4. No cross-encoder (512 MB / unproven ROI).
5. No title-aware reindex (would need a separate collection; not justified by current A/B).
