# Dataset plan (Phase 0)

## Assignment attachment

The specification says to use “the dataset attached to this assignment,” but **no dataset file is attached** in this workspace. Only public dataset links are listed. This project therefore uses the permitted public + synthetic path.

## Part A — Bulk corpus (HotpotQA distractor)

| Field | Plan |
| --- | --- |
| Source | [`hotpotqa/hotpot_qa`](https://huggingface.co/datasets/hotpotqa/hotpot_qa) config **`distractor`** (also downloadable from [hotpotqa.github.io](https://hotpotqa.github.io/)) |
| License | **CC BY-SA 4.0** — attribute HotpotQA authors; share-alike for derivatives |
| Access (28 Oct 2026) | Public on Hugging Face; no gated access observed for standard download |
| Record definition | Each unique context paragraph → independent text record `{id: "hotpotqa:<title>", title, text, meta}` |
| Target count | ≥ **55,000** unique records (buffer above DATA-1’s 50,000) |
| Selection | Seeded, deterministic `scripts/build_corpus.py`; justify subset in this file after build |
| Evaluation coupling | Eval questions drawn so gold supporting paragraphs are in the corpus; unanswerable set built by **removing** selected gold paragraphs before index |

Feasibility: train+validation distractor contexts contain far more than 55k paragraph instances; after exact-title dedup we still expect to clear 55k. Exact/near-duplicate rates will be reported from the real build.

## Part B — Synthetic enterprise corpus

Seeded generator (no LLM ground truth): multi-service payment-processing style docs in **md / pdf / docx / html / txt / csv**, with planted contradictions, incompleteness, duplicates, unanswerable asks, and prompt-injection samples. Ground truth in `data/manifests/synthetic_truth.json`.

## Storage fit (pre-measure estimate)

Short Hotpot paragraphs → Neon **1 GB** and Qdrant Free **4 GB disk / 1 GB RAM** are expected to suffice for ≥50k records **if** Postgres stores text once and Qdrant uses 384-d vectors + on-disk options as needed. **No count or footprint claim is final until `scripts/verify_counts.py` evidence exists.**

## Rejected / deferred public sets

| Dataset | Why not primary |
| --- | --- |
| RAGBench | Mixed sources; less uniform gold for our metrics |
| 2WikiMultihopQA | Similar multi-hop value; doubles preprocessing |
| danluu/post-mortems | Mostly external links; crawl fragility/copyright — replaced by synthetic incidents |
