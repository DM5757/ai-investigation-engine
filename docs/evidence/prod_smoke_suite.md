# Production smoke suite results

- Base: `https://ai-investigation-engine-scyz.onrender.com`
- ACTIVE documents: **55,081**
- Suite script: `scripts/prod_smoke_suite.py`

## Milestone 3 acceptance (`428ed09`)

| Case | Status | ms | cites | Verdict |
| --- | --- | ---: | ---: | --- |
| airport | answered | 74931 | 1 | PASS — Woodrum Field / Roanoke, VA |
| multi_doc_payment | llm_unavailable | 186629 | 5 | DEGRADED — `groq:daily_quota`; correct synthetic titles |
| multihop_ohio_csudh | answered | 232129 | 3 | FAIL — abstention-like answer; Mansfield Campus cites |
| contradiction_deploy | answered | 149740 | 2 | PASS — 08:10 vs 14:00 UTC |
| unanswerable_fraudscorer | insufficient | 190914 | 0 | PASS — honest abstention |
| colony_regression | timeout | 300266 | — | FAIL — client timeout before retrieval wall-clock gate |

### Measured stage latency (airport @ `428ed09`)

| Stage | ms |
| --- | ---: |
| plan | 1,388 |
| tools_seed_search | 64,915 |
| tools_llm_round_0 | 801 |
| synthesize | 486 |
| request total | 67,591 |

Retrieval dominated successful latency before the candidate-pool change.

## Follow-up retest (`fecabea`)

| Case | Status | ms | cites | Verdict |
| --- | --- | ---: | ---: | --- |
| airport | answered | 66851 | 1 | PASS — Woodrum Field; seed search ~12s |
| colony_regression | insufficient | 47992 | 0 | PASS — abstains; no unrelated Hotpot previews |

### Measured stage latency (airport @ `fecabea`)

| Stage | ms |
| --- | ---: |
| plan | 1,046 |
| tools_seed_search | 11,656 |
| tools_llm_round_0 | 44,715 |
| synthesize | 1,081 |
| request total | 58,498 |

After shrinking dense/sparse pools and gating retrieval on wall-clock, seed retrieval dropped from ~65s to ~12s. Remaining airport latency is mainly one LLM tool round.

## Before / after

| Metric | Before (c03b155 era) | After (`fecabea`) |
| --- | ---: | ---: |
| Airport factual | ~142s | ~67s |
| Colony regression | timeout / llm_unavailable | insufficient @ ~48s |
| False zero `trace.latency_ms` | present | fixed (monotonic per-stage) |
| Daily quota handling | retried until hang | `daily_quota` fail-fast + failover |

## Earlier baselines

- `c03b155`: airport PASS @ 142s; several later cases provider-limited.
- `04153fe`: exhausted-provider retest — honest `llm_unavailable`, improved payment titles, colony preview cites 0.

Full machine-readable record: `docs/evidence/prod_smoke_suite.json`.
