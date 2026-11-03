# Sealed evaluation status — `sealed_final_v1`

**Updated:** 2026-11-03
**Status:** incomplete / inconclusive — **not a final accuracy result**

## What happened

- Evaluation stopped after free-tier Groq `daily_quota` and Gemini `rate_limit_rpm`.
- Candidate had 40 slots marked completed; **38** were genuine LLM outcomes;
  **2** were `llm_unavailable` incorrectly marked completed (now reclassified to **failed**).
- Legacy checkpoint retained; deterministic zero-LLM outcomes are valid for the legacy path.
- Remaining sealed IDs stay **pending**. Evaluation was **not** resumed.

## Bookkeeping repair

- Reclassified candidate IDs: `phaseb_hotpot_5ac3caa15542995ef918c23a, phaseb_hotpot_5a7c97e15542990527d554db`
- Poisoned cache files removed: 4
- Harness updated so future `llm_unavailable` results count as failures, not completions.

## Production

- Experimental passage reader remains **disabled** by default.
- Incomplete sealed results must not be advertised as production quality.

