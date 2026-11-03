# Final candidate freeze (engineering push)

**Status:** Frozen on development evidence. **Sealed evaluation not executed** (provider quotas exhausted at freeze time). **Production flag remains off.**  
**Date:** 2026-11-03  
**Code basis:** post–Phase C.1 SOFT candidate + paraphrase/passage entailment + bridge retrieval

## Frozen knobs

| Knob | Value |
| --- | --- |
| Feature flag | `EXPERIMENTAL_PASSAGE_READER=false` (prod default; promote only after sealed + canary) |
| Multi-hop policy | `soft` (`READER_MULTI_HOP_POLICY=soft`) |
| Coverage threshold | `0.65` |
| Bridge rounds | `1` (`READER_MAX_BRIDGE_ROUNDS=1`) |
| Preferred retrieval (reader path) | `hybrid_rrf` (`READER_PREFERRED_MODE=hybrid_rrf`) |
| Prompt | `reader_v2_phase_c` |
| Verify | `verify_final_v1` (paraphrase variants + cited-passage secondary support) |
| Reader | `structured_reader_v2` |
| Eval / sealed retrieval | `hybrid_rrf`, k=10 |
| Benchmark sealed | `phase_b_bench_v1_test_sealed.json` (untouched; not scored) |

## Architecture changes vs Phase C.1

1. **Iterative bridge retrieval** — when SOFT returns `partial`/`insufficient` with `next_query`, run one extra `search_documents` + read and keep the better verified outcome.
2. **Paraphrase-aware support** — normalize middle initials / parentheticals; if quotes alone miss coverage but a **valid quote exists**, allow answer coverage against the **cited passage bodies**.
3. **Retrieval default for reader path** — API uses `hybrid_rrf` when the experimental flag is on and the client omits `mode` (legacy default `hybrid_rerank` unchanged when flag is off).

## Development evidence (matched slice)

Run: `final_dev_v1` (`eval/results/final_dev_v1__comparison.json`), n≈27–30 scored (Hotpot limit 20 + robustness); Groq daily quota + Gemini RPM caused some skips.

| Config | Full F1 | Raw F1 | Supported | Full answered | Partial | Unsupported full | Multi-hop all-gold | Contra recall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `final_oracle_soft` | 0.357 | 0.505 | 0.630 | 0.481 | 0.148 | **0.0** | **0.684** | 1.0 |
| `final_raw_soft` | 0.259 | 0.419 | 0.481 | 0.296 | 0.185 | **0.0** | 0.400 | 1.0 |
| `final_legacy` | 0.0* | 0.156 | 0.233 | 0.233 | 0.0 | 0.233 | 0.0 | 1.0 |

\*Legacy run heavily degraded by `llm_unavailable` (9/30); not a clean head-to-head on answer F1.

Retrieval A/B (`final_retr_ab_v1`, n=40 Hotpot): `hybrid_rrf` = `hybrid_rerank` on all-gold@K (0.825) / recall (0.912); **select `hybrid_rrf`** (latency + Phase A heldout all-gold).

## Pre-registered acceptance (dev)

| Criterion | Result |
| --- | --- |
| Unsupported full-answer rate ≤ 0.02 | **Pass** (0.0 oracle & raw) |
| False-answer on robustness / abstention controls ≤ 0.05 | **Pass** (0.0; correct abstention 1.0) |
| Appropriate status on must-abstain ≥ 0.95 | **Pass** (1.0) |
| Multi-hop all-gold cited ≥ 0.50 on **oracle** answered items | **Pass** (0.684) |
| Contradiction recall ≥ 0.80; false-contradiction ≤ 0.20 | **Pass** (1.0 / 0.0) |

## Promotion gate

1. Execute `eval/run_sealed_final.py --confirm-sealed-unlock YES` **once** when LLM quota allows full sealed coverage (or document exclusions).
2. Require sealed candidate to meet the same safety criteria vs frozen legacy baseline.
3. Canary: set `EXPERIMENTAL_PASSAGE_READER=true` on Render; verify `/api/version` SHA; sample live investigations; keep rollback = flag false.

**Do not promote on development evidence alone.**

## Rollback

`EXPERIMENTAL_PASSAGE_READER=false` (default). Legacy `_finalize` unchanged. No corpus/index changes.

## Sealed integrity

- Sealed SHA recorded at unlock time by `run_sealed_final.py`.
- Do not modify prompts, policy, thresholds, or retrieval after unlock based on sealed answers.
