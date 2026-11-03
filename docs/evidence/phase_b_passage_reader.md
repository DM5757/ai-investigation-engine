# Phase B — Passage Reader & E0 Decisive Experiments

**Date:** 2026-11-03  
**Scope:** Expanded disjoint benchmark, experimental quote-verified passage reader, E0 A/B/C + LLM baseline on **development** data only.  
**Not in scope:** Sealed-test evaluation; production default change; corpus reindex; paid infra.

## 1. Benchmark — `phase_b_bench_v1`

| Split | Target | Actual | Notes |
| --- | ---: | ---: | --- |
| Development | ≥150 | **150** | Hotpot bridge/comparison + levels; unused vs legacy/heldout/demos |
| Sealed test | ≥300 | **300** | Frozen; **not evaluated** in Phase B |
| Robustness (dev) | independent packs | **5** | Synthetic only (ablated unanswerable ×2, contradiction ×2, non-conflict control) |

- Seed `20261103`; SHA-256 manifests in `eval/questions/phase_b_bench_v1_manifest.json`.
- Eligible unused Hotpot with ACTIVE gold titles: **8685** → near-dedupe cap **530** → split.
- Type mix after stratification fix: dev bridge/comparison **104/46**; sealed **209/91**; levels preserved.
- Robustness limited to carefully labeled synthetics (not fabricated Hotpot). Ablated items drop gold from query context; query-overlay contradictions are not indexed.

Prior `heldout_v1` / legacy sets remain diagnostic, not fresh final evidence.

## 2. Experimental reader

- `app/investigation/reader.py` + `app/llm/prompts/reader.py`
- Flag: `EXPERIMENTAL_PASSAGE_READER` (**default false**). Legacy finalize is production path.
- One structured LLM call → deterministic label/quote verification + answer↔quote support.
- Injection scan on passage text; unsupported claims → abstention.
- Engine hook: `_finalize_with_reader` when flag enabled.

## 3. E0 protocol

| Config | Evidence | Reader |
| --- | --- | --- |
| E0-A `e0_oracle` | Hotpot gold paragraphs | Structured + verify |
| E0-B `e0_raw` | Top-10 `hybrid_rrf` (no claim filter) | Structured + verify |
| E0-C `e0_legacy` | Current investigation pipeline | Heuristic extract/synth |
| `e0_llm_baseline` | Same raw top-10 | Free-form LLM, weak verify |
| `e0_oracle_shuffle` | Gold paragraphs, texts shuffled | Structured + verify |

Retrieval for E0: `hybrid_rrf`, k=10 (prod default remains `hybrid_rerank`).  
Cache/checkpoints under `data/cache/e0_reader/` and `data/checkpoints/e0_reader/` (gitignored).

Model settings recorded in result JSON (`groq_model`, `gemini_model`, temperature 0.0, `prompt_id=reader_v1`).

## 4. Results

### Pilot `e0_pilot_v1` (n=12 Hotpot; pre-fix bridge-only slice)

| Config | n | token F1 | EM | answer_supported | mean tokens | p50 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| e0_oracle | 12 | **0.769** | **0.583** | 0.917 | 861 | 0.9s |
| e0_raw | 12 | **0.710** | **0.667** | 0.833 | 1998 | 12.1s |
| e0_legacy | 12 | 0.191 | 0.000 | 0.917* | 1168 | 10.2s |
| e0_llm_baseline | 12 | 0.217 | 0.000 | 0.000 | 1642 | 10.5s |

\*Legacy “supported” = status answered (not quote-verified).

### Scaled `e0_dev_v1` (40 Hotpot + 5 robustness; balanced types)

**All attempted (incl. robustness):**

| Config | n scored/attempted | token F1 | EM | supported | cite F1 | multi-hop all-gold cited | provider fails |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| e0_oracle | 45/45 | 0.573 | 0.467 | 0.644 | 0.778 | 0.333 | 0 |
| e0_raw | 45/45 | 0.477 | 0.378 | 0.622 | 0.731 | 0.278 | 0 |
| e0_legacy | 45/45 | 0.107 | 0.022 | 0.667* | 0.396 | 0.108 | 0 |
| e0_llm_baseline | 16/21 | 0.154 | 0.000 | 0.000 | 0.812 | 0.562 | 5 (stopped) |
| e0_oracle_shuffle | 43/45 | 0.515 | 0.419 | 0.628 | 0.800 | 0.400 | 2 |

**Paired Hotpot-only (n=40 common, no errors):**

| Config | token F1 | EM | supported | cite F1 | multi-hop |
| --- | ---: | ---: | ---: | ---: | ---: |
| e0_oracle | **0.645** | **0.525** | 0.725 | 0.778 | 0.333 |
| e0_raw | **0.530** | **0.425** | 0.675 | 0.740 | 0.294 |
| e0_legacy | 0.116 | 0.025 | 0.700* | 0.402 | 0.088 |

Raw retrieval `all_gold@10` on scored raw rows ≈ **0.79**.

Bootstrap 95% CIs (oracle all-attempted F1): see `token_f1_ci` in result JSON (n=45 still wide).

### Robustness (qualitative + scores)

| Item | Reader (oracle/raw) | Legacy |
| --- | --- | --- |
| Unanswerable ablated | Correct abstention (`insufficient`) | **False answers** (`answered`) |
| Query-overlay contradiction | Abstains (`insufficient`; missing_info often empty → auto flag 0) | Partial / no clean conflict flag |
| Planted deploy contradiction | No oracle passages for synthetic titles; raw abstains | Detects `conflicting` |
| Non-conflict control | Often abstains / thin answer | Partial |

### Efficiency / quota

- Reader path: **1 LLM call**/question; oracle ~750–860 tokens; raw ~1.8–2.0k tokens.
- Legacy: multi-stage; lower F1 despite similar or lower token totals.
- Groq **daily_quota** hit mid `e0_legacy`/`e0_llm_baseline`; Gemini **rate_limit_rpm** stopped baseline early. Progress preserved via checkpoints. No paid upgrades.

### Shuffle control

F1 remains relatively high after shuffling passage *texts* across titles (0.515 vs oracle 0.573). Interpretation: answer strings can still be recovered from swapped text; **title-faithful multi-hop citation** is the stricter dependence check (oracle multi-hop completeness only ~0.33). Phase C should harden conflict labeling and multi-doc cite requirements.

## 5. Decision (development evidence)

1. **Oracle is good enough** (paired F1 0.645 / EM 0.525) — reader + verification work when evidence is complete; remaining misses are over-abstention / multi-hop cite gaps, not total failure.
2. **Retrieval costs ~0.11 F1** vs oracle on the paired set (0.645 → 0.530); `all_gold@10` ≈ 0.79 — coverage is imperfect but not the main cliff.
3. **Legacy heuristic pipeline is the large cliff** (0.530 → 0.116 F1; EM 0.425 → 0.025).
4. **Quote verification improves faithfulness** vs LLM baseline (supported 0.62–0.92 vs 0.00; baseline EM 0 on completed rows).
5. **Reader abstains better on unanswerable** than legacy (which over-answers).
6. **Multi-hop completeness** still weak (~0.29–0.33) — Phase C should require citing all required gold docs when answerable.
7. **Cost:** +~1 structured call and higher prompt tokens vs claim-filter path, justified by ~4–5× F1 lift on this development slice.

**Verdict:** A passage reader is **justified** for Phase C behind the existing flag. Do **not** flip the production default yet. Do **not** score the sealed test until a single locked config is chosen.

## 6. Proposed Phase C

1. Keep `EXPERIMENTAL_PASSAGE_READER=false` on Render.
2. Harden multi-hop cite completeness + explicit contradiction status in the schema.
3. Optional hybrid: reader over retrieved passages, legacy only as fallback when reader abstains with `next_query`.
4. Shadow/canary on a small internal slice; one sealed unlock after freeze.
5. No 55k reindex; preserve Neon/Qdrant consistency and free-tier budgets.

## 7. Artifacts

- Questions: `eval/questions/phase_b_bench_v1*.json`
- Results: `eval/results/e0_pilot_v1__*.json`, `eval/results/e0_dev_v1__*.json`
- Harness: `eval/run_e0_reader.py`
- Builder: `scripts/build_phase_b_benchmark.py`
