# Sealed evaluation infrastructure (post-freeze)

**Date:** 2026-11-03  
**Frozen candidate unchanged:** `9f20864` knobs — SOFT / 0.65 / `hybrid_rrf` / `verify_final_v1` / bridge=1.  
**Production default:** `EXPERIMENTAL_PASSAGE_READER=false` (unchanged).

## Fixes

1. **Bookkeeping** — every expected sealed ID is `pending|completed|failed`; early stop no longer drops the tail. `sealed_test_evaluated` / `sealed_complete` require all IDs terminal and ≥1 completed per required config.
2. **Candidate fidelity** — `sealed_candidate_soft` runs `InvestigationEngine` with experimental reader + bridge rounds=1 (production-equivalent when the flag is on). Legacy keeps the flag off.
3. **Budgets / pause / resume** — `--max-requests-today`, `--max-tokens-today`, `--max-questions-this-session`, `--pause`, `--resume`; provider backoff on failures; checkpoints under `data/checkpoints/sealed_final/`.
4. **Fingerprints** — config / prompt / sealed / freeze / corpus hashes persisted; resume rejects drift.
5. **Cache validity** — sealed cache keys include model, config fingerprint, prompt SHA, verify id; mismatched prompt/verify ignored.
6. **`/api/version`** — reports effective reader mode and bridge/policy/coverage/preferred mode (no secrets).

## Safe multi-day command

```bash
uv run python eval/run_sealed_final.py \
  --confirm-sealed-unlock YES \
  --run-id sealed_final_v1 \
  --resume \
  --pause-s 1.5 \
  --max-requests-today 200 \
  --max-tokens-today 180000 \
  --max-questions-this-session 40 \
  --stop-after-llm-unavailable 5 \
  --provider-backoff-s 15
```

Omit `--resume` on the first session only. Exit code `10` means incomplete (expected until all IDs are terminal).

Sealed questions were **not** evaluated in this infrastructure change.
