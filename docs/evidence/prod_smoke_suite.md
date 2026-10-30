# Production smoke suite results

- Base: `https://ai-investigation-engine-scyz.onrender.com`
- ACTIVE documents: **55,081**
- Suite script: `scripts/prod_smoke_suite.py`

## Verified passes (deploy `c03b155`)

| Case | Status | ms | cites | Verdict |
| --- | --- | ---: | ---: | --- |
| airport (regression B) | answered | 142242 | 1 | PASS — Woodrum Field / Roanoke, VA |
| budget_isolation_1→2 | llm_unavailable → answered | 136k / 178k | 2 / 1 | PASS — per-request budget isolation |

## Baseline failures / degraded (`c03b155`)

| Case | Status | Notes |
| --- | --- | --- |
| multi_doc_payment | insufficient | Keyword-hint truncation dropped `payment`/`march` (fixed in `04153fe`) |
| multihop_ohio_csudh | timeout | Client 330s while providers retrying |
| unanswerable_fraudscorer | timeout | Same |
| contradiction_deploy | llm_unavailable | Honest degraded; correct synthetic docs retrieved |
| colony_regression | llm_unavailable | Honest degraded; previously surfaced unrelated Hotpot titles |

## Post-fix retest (`04153fe`, providers exhausted)

| Case | Status | cites | Notes |
| --- | --- | ---: | --- |
| multi_doc_payment | llm_unavailable | 4 | Titles now present: Exec Summary + Incident Report |
| colony_regression | llm_unavailable | **0** | Weak unrelated previews filtered |
| unanswerable_fraudscorer | llm_unavailable | 0 | Honest degraded (insufficient path not reached) |

Full machine-readable record: `docs/evidence/prod_smoke_suite.json`.
