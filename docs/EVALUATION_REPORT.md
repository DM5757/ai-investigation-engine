# Evaluation Report

**Project:** Applied AI Investigation Engine  
**Date:** 2026-10-29  
**Status:** Preliminary — active corpus below 50k at measurement time. Re-run after bulk ingest completes.

## 1. Dataset and question construction

### Evaluation set

- Builder: `scripts/build_eval_questions.py`
- Artifact: `eval/questions/eval_set.json` (**75 questions**, seed **42**)
- Splits: `eval/questions/dev_split.json` (29) / `test_split.json` (46)
- Type mix (approx.): factual, multi_hop, multi_doc, multi_step, contradiction, unanswerable

### Provenance

| Source | Role |
| --- | --- |
| HotpotQA distractor **validation** (CC BY-SA 4.0) | Multi-hop / multi-doc / factual questions whose supporting titles exist in `data/raw/corpus.jsonl` |
| `data/manifests/synthetic_truth.json` | Contradiction pairs, incompleteness / unanswerable topics, gold span markers, enterprise multi-doc questions |

Gold answers for Hotpot items are the dataset answers (not LLM-generated). Synthetic golds are planted strings / expected statuses (`INSUFFICIENT`, `CONFLICTING`).

### Corpus under test

Indexed Hotpot paragraphs + synthetic enterprise docs in **Neon + Qdrant**. Exact ACTIVE counts are always taken from `docs/evidence/dataset_counts.json` / eval comparison payloads — never invented.

At preliminary runs below, ACTIVE ≈ **2.1k–2.2k** documents (`preliminary: true`). Many Hotpot gold titles are not yet indexed, so retrieval metrics are computed only on questions whose gold docs resolve in Postgres.

## 2. Methodology

Harness: `eval/run_eval.py` (resumable checkpoints under `data/checkpoints/eval/`).

| Config | Pipeline | Retrieval mode | Purpose |
| --- | --- | --- | --- |
| `dense_only` | retrieval_only | dense | Dense vs hybrid |
| `hybrid_rrf` | retrieval_only | hybrid_rrf | Dense vs hybrid |
| `baseline_rag` | baseline_rag | hybrid_rrf | Single-shot retrieve + synthesize |
| `full_investigation` | investigation | hybrid_rrf | Full multi-step engine |

**Metrics (deterministic primary):** Recall@K, MRR, All-gold@K, multi-doc coverage, exact match, token F1, citation precision/recall/F1, correct abstention, contradiction detection, latency, LLM calls/tokens.

DOC-6 chunking comparison (fixed_window vs structure_aware) was measured earlier: `eval/results/chunking_comparison.json`.

## 3. Results

### 3.1 Retrieval — dense vs hybrid (`prelim_retrieval_v2`)

Evidence: `eval/results/prelim_retrieval_v2__comparison.json`  
Corpus ACTIVE **2232**. Questions with resolved gold docs: **n=7** (mostly synthetic + early corpus overlap).

| Config | Recall@10 | MRR | All-gold@10 | Multi-doc coverage | Mean latency (s) |
| --- | --- | --- | --- | --- | --- |
| dense_only | **1.00** | 0.67 | **1.00** | **1.00** | 0.13 |
| hybrid_rrf | 0.86 | **0.86** | 0.71 | 0.86 | 0.22 |

**Reading:** On this small resolved subset (synthetic-heavy), dense recall is perfect while hybrid trades a bit of recall for better MRR. **Do not extrapolate to the full Hotpot corpus** until more gold titles are ACTIVE and n ≫ 7.

Earlier v1 (`prelim_retrieval_v1`, ACTIVE 1806, n=6 resolved) showed the same qualitative pattern (dense Recall@10=1.0; hybrid MRR competitive).

### 3.2 Answer quality — baseline RAG vs investigation (`prelim_answer_v1`)

Evidence: `eval/results/prelim_answer_v1__comparison.json`  
Corpus ACTIVE **2114**. Test subset **n=20** (factual / multi_doc / contradiction / unanswerable / multi_step filter).

| Config | Token F1 | Citation F1 | Correct abstention | Contradiction detect | Mean latency (s) | Mean LLM calls |
| --- | --- | --- | --- | --- | --- | --- |
| baseline_rag | 0.017 | 0.078 | 0.00 | 0.00 | 6.49 | 0.80 |
| full_investigation | 0.015 | 0.10 | **1.00** | 0.00 | 0.20 | 0.00 |

**Reading:**

- Exact-match is near zero: Hotpot/synthetic answers are free-form; token F1 is the fairer lexical metric and remains low on this incomplete corpus.
- **Investigation abstained correctly** on unanswerable items in this run (rate 1.0) but recorded **0 LLM calls** — behavior matches the **degraded / heuristic path** (retrieve + sufficiency) rather than a full live tool loop for every item. Baseline RAG did call the LLM (~0.8 calls/question) with higher latency.
- Contradiction detection rate 0.0 in both configs on the sampled contradiction items: planted conflicts were not surfaced as `conflicting` in this preliminary pass (retrieval may not have jointly ranked both sides, or synthesis stayed non-conflict). Unit/scripted contradiction tests remain green; **live contradiction coverage is a known gap**.

### 3.3 Chunking strategies (DOC-6)

Evidence: `eval/results/chunking_comparison.json`

| Strategy | Avg chunks/doc | Span Recall@5 (synthetic markers) | Hotpot proxy Recall@5 |
| --- | --- | --- | --- |
| fixed_window | **1.12** | 1.0 | 1.0 |
| structure_aware | 1.46 | 1.0 | 1.0 |

**Decision:** `fixed_window` wins on chunk count with tied proxy recall; production default remains `structure_aware` for heading context (documented trade-off).

## 4. Failure analysis

1. **Unresolved Hotpot golds** — Most multi-hop questions lack ACTIVE supporting docs until bulk ingest passes their titles → retrieval scores exclude them. Fix: continue ingest; re-run `prelim_retrieval_*` when ACTIVE ≥ 50k or when a title-filtered subset is fully indexed.
2. **Low answer F1** — Incomplete evidence + free-form answers; lexical match under-penalizes semantically correct paraphrases. Optional LLM-judge was deferred to protect free-tier quotas.
3. **Contradiction live miss** — Need joint retrieval of both conflicting docs and explicit conflict adjudication in the evaluated path.
4. **Investigation LLM underuse in prelim_answer_v1** — Degraded path dominated; verify gateway rate limits / budgets when re-running full investigation eval.
5. **Citation F1 low** — Gold doc id resolution depends on title/path maps; synthetic filenames vs titles can undercount even when quotes are valid.

## 5. Limitations and next improvements

- Label all current numbers **preliminary** until `dataset_counts.json` shows `meets_data1_50k`.
- Re-run retrieval on gold-resolved Hotpot subset after ingest catches supporting titles.
- Force live investigation eval with explicit non-degraded checks; log provider errors.
- Add human calibration sample for citation / contradiction judgments.
- Cache LLM responses in Postgres `llm_cache` more aggressively during multi-day eval.

## 6. Evidence index

| Artifact | Path |
| --- | --- |
| Question set | `eval/questions/eval_set.json` |
| Retrieval comparison | `eval/results/prelim_retrieval_v2__comparison.json` |
| Answer comparison | `eval/results/prelim_answer_v1__comparison.json` |
| Chunking DOC-6 | `eval/results/chunking_comparison.json` |
| Corpus counts | `docs/evidence/dataset_counts.json` |
| Metrics unit tests | `tests/unit/test_eval_metrics.py` |
