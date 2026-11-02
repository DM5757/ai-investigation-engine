# Phase A — Evaluation Integrity & Evidence-Retention Instrumentation

**Date:** 2026-11-02  
**Scope:** Scoring fixes, retrieval-mode alignment measurement, retention probes, held-out redesign.  
**Not in scope:** Passage reader / Phase B answer-quality redesign. Production default retrieval mode unchanged.

## 1. Audit findings — confirmed / refuted

| # | Claim | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | EM/token F1 includes citation markers `[S1]` | **CONFIRMED** | `eval/metrics.py` previously punct-stripped `[S1]` → token `s1`. Demo: `Woodrum Field [S1]` F1=0.8 vs gold. |
| 2 | Citation verification misses alternate formats | **CONFIRMED** | `_CITE_RE = \[ (S\d+) \]` missed `[S1, S2]` (empty match). Production answers use grouped cites. |
| 3 | Prod default `hybrid_rerank` vs eval `hybrid_rrf` | **CONFIRMED** | `routes_query.py` default `hybrid_rerank`; M5–M7 answer eval configs `hybrid_rrf`. |
| 4 | Test set reused for tuning | **CONFIRMED** | M6/M7 iterated on the same 62-question test split (`docs/PROGRESS.md`, `m6_*`/`m7_*` artifacts). |
| 5 | Hotpot labeled factual via answer length | **CONFIRMED** | `build_eval_questions.py`: `len(answer.split()) <= 4 → factual`, ignoring Hotpot `type`. |
| 6 | Investigation drops required docs after retrieval | **CONFIRMED (partial)** | Retention probe: gold recall 0.81 → 0.56 after claim filtering → 0.31 at citations (`phase_a_retention.json`). |
| 7 | Demo-specific geography/entity logic | **PARTIAL** | No hardcoded CSUDH/Lent/Woodrum branches. General US `state_westness` table + geo cue regex includes `columbus`/`carson`/`ohio`/`california` (`engine.py` `_prioritize_claims`) — demo-biased but not single-case hardcodes. |

## 2. Bugs fixed (scoring / verification)

1. **Citation-aware answer normalization** for EM/token F1 (`strip_citation_markers`).
2. **Shared citation parser** (`app/investigation/citations.py`): grouped, adjacent, fullwidth, invisible separators; malformed `[Source1]` / `[A1]` rejected.
3. **Verifier + synthesizer** use the shared parser (production cite prune now sees `[S1, S2]`).
4. **Re-score of frozen predictions** without changing outputs (`scripts/rescore_eval_predictions.py`).

## 3. Original vs corrected metrics (M7 predictions unchanged)

Artifact: `eval/results/m7_test_adapt_v3__full_investigation__rescored_cite_strip.json`  
Source predictions: `m7_test_adapt_v3__full_investigation.json` (preserved).

| Metric | Legacy (with cite tokens) | Corrected (cites stripped) | Delta |
| --- | ---: | ---: | ---: |
| token F1 (n=62) | **0.183** | **0.223** | +0.040 |
| exact match (n=62) | **0.000** | **0.145** | +0.145 |

**Interpretation:** Scoring correction only — not a model improvement. Historical M7 reports should quote both.

## 4. Production vs evaluation retrieval (same corpus/questions/K)

Run: `phase_a_retrieval_v1` — legacy **test** split, k=10, ACTIVE 55081, n_scored=60.

| Mode | Recall@10 | MRR | all-gold@10 | mean latency (s) |
| --- | ---: | ---: | ---: | ---: |
| dense_only | 0.908 | 0.914 | 0.833 | 0.105 |
| hybrid_rrf | **0.925** | 0.939 | **0.850** | 0.109 |
| hybrid_rerank (prod default) | 0.858 | **0.958** | 0.717 | 0.213 |

**Conclusion:** Production reranker improves MRR but reduces set coverage (R@10 / all-gold). **Do not change the production default** until a deliberate trade-off decision; future answer eval should report the mode actually used.

## 5. Evidence-retention loss by stage

Probe: `docs/evidence/phase_a_retention.json` (8 multi-gold diagnostic cases, `hybrid_rerank`, gold applied only post-hoc).

| Stage | Mean gold-doc recall | Mean loss |
| --- | ---: | ---: |
| initial_retrieval | 0.812 | 0.188 |
| evidence_pool | 0.812 | 0.188 |
| claim_extraction | 0.812 | 0.188 |
| **claim_filtering** | **0.562** | **0.438** |
| sufficiency / final selected | 0.562 | 0.438 |
| **actual_citations** | **0.312** | **0.688** |

Primary drop: question-focus claim filtering. Secondary drop: citation prune-to-answer. Instrumentation: `EVAL_RECORD_RETENTION` / `--record-retention` (no gold into the engine; no passage text in ordinary logs).

## 6. Held-out evaluation design

- Legacy `eval_set.json` (94 q; test 62): **development/diagnostic only** — contaminated by M6/M7 tuning.
- New: `eval/questions/heldout_v1.json` — **85** questions (dev 26 / **frozen test 59**).
  - Hotpot: native `id` + `type` (`bridge`→`multi_hop`, `comparison`→`multi_doc`); excludes all 94 legacy question texts; ACTIVE gold titles required.
  - Synthetic: **3** unanswerable + **2** contradiction (still small-n — do not overclaim).
- Rule: **do not tune against frozen heldout_v1 test answers.**

## 7. Security

- `.env` is gitignored; not present in `git ls-files`.
- No credential rotation performed.
- Live demo behavior otherwise preserved; citation parser is a correctness fix only.

## 8. Recommended Phase B experiment

**Passage-level verified LLM reader** gated by retention metrics:

1. When gold-capable docs are in `evidence_pool` but lost at `claim_filtering`, run a quote-constrained reader over retained passages (not free-form corpus chat).
2. Require every generated claim span to be a verified substring of a retrieved chunk.
3. Measure on **heldout_v1 test only** (once): token F1 / EM (cite-stripped), citation F1, retention recall at citations, vs current adaptive baseline on the **same** retrieval mode as production (`hybrid_rerank`).
4. Success criterion: lift cite-stripped F1 and gold-citation recall without regressing abstention/contradiction on the expanded synthetic set.

Do not implement Phase B until this report is reviewed.
