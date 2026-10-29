# Dataset plan (Phase 6 update)

## Assignment attachment

The specification says to use “the dataset attached to this assignment,” but **no dataset file is attached** in this workspace. Only public dataset links are listed. This project therefore uses the permitted public + synthetic path.

## Part A — Bulk corpus (HotpotQA distractor)

| Field | Status |
| --- | --- |
| Source | [`hotpotqa/hotpot_qa`](https://huggingface.co/datasets/hotpotqa/hotpot_qa) config **`distractor`** via HF parquet + pyarrow (`scripts/build_corpus.py`) |
| License | **CC BY-SA 4.0** — attribute HotpotQA authors; share-alike for derivatives |
| Record definition | Each unique context paragraph → `{id: "hotpotqa:<title>", title, text, meta}` |
| Build | Seeded (`seed=42`), deterministic shuffle; `--limit` for pilots; `--target 55000` for full |
| Manifest | `data/manifests/corpus_manifest.json` (sha256, load method, counts) |
| Offline fallback | `data/samples/hotpot_sample.jsonl` if all download paths fail (HUMAN ACTION in manifest) |

**Subset justification:** Target **55,000** unique titles (buffer above DATA-1’s 50,000). The Hotpot **validation** distractor split alone yields **66,581** unique titles after dedup (measured 2026-10-29); the build caps to 55,000 with `seed=42`. Train shards remain cached under `data/cache/hotpot_hf/` if a larger pool is needed later. Exact count and sha256 are only those written in the manifest after a successful build — never invent counts.

## Part B — Synthetic enterprise corpus

Seeded generator (`scripts/generate_synthetic.py`): **md / pdf / docx / html / txt / csv / jsonl** under `data/synthetic/`, with planted contradictions, incompleteness, prompt-injection, and gold span markers for DOC-6. Ground truth: `data/manifests/synthetic_truth.json`.

## Storage fit (measured pilot → estimate)

See `docs/evidence/pilot_ingest.json` and `docs/evidence/storage_estimate_55k.json`.

Hard rule: no “fits free tier / ≥50k indexed” claim without `docs/evidence/dataset_counts.json` against live Neon + Qdrant.

## Rejected / deferred public sets

| Dataset | Why not primary |
| --- | --- |
| RAGBench | Mixed sources; less uniform gold for our metrics |
| 2WikiMultihopQA | Similar multi-hop value; doubles preprocessing |
| danluu/post-mortems | Mostly external links; crawl fragility/copyright — replaced by synthetic incidents |
