# Milestone 7 — M6 failure audit (held-out test, adaptive)

Source: `eval/results/m6_test_adapt_v1__full_investigation.json` (n=62).  
Categories assigned by comparing status, gold answer, token F1, and citation overlap — not guessed.

## Distribution

| Category | Count |
| --- | ---: |
| Unnecessary abstention | 25 |
| Correct / near wording (F1≥0.5 or gold contained) | 17 |
| Wrong answer — missing all gold docs | 7 |
| Wrong / incomplete multi-hop relation | 5 |
| Partial overlap (0&lt;F1&lt;0.5) | 3 |
| Abstention OK (unanswerable) | 2 |
| Contradiction OK | 1 |
| Missed contradiction | 1 |
| Wrong answer (other) | 1 |
| False contradiction | 0 |
| Provider / runtime error | 0 |

## By question type

| Type | Dominant failure |
| --- | --- |
| factual (51) | Unnecessary abstention (22); missing gold docs (7); incomplete multi-hop-style factual (5) |
| multi_doc (3) | Unnecessary abstention (2); partial (1) |
| multi_hop (3) | All correct/near |
| contradiction (2) | 1 OK (deploy time), 1 missed (root cause) |
| unanswerable (2) | Both OK |
| multi_step (1) | Unnecessary abstention |

## Primary mechanisms

1. **Claim filter too strict** — multi-token focus phrases like "March incident" miss verbatim; soft technical tokens (AuthGateway / misconfigured) were capped at 0.35 → empty supporting set.
2. **Comparison entity extraction** — `or`-clause trail-junk stripping dropped real names (Tamiami Canal, Marcel Duchamp).
3. **Missed causal contradiction** — JWT TTL vs Neon pool is competing causation, not polarity; temporal-only detector missed it; marker span answered ALPHA-OUTAGE-0810 instead.
4. **Retrieval miss** — 7 items cite no gold docs (upstream recall), not synthesis alone.

## Tuning note

Fixes developed against these mechanisms and checked on **dev**; held-out test reported once for M7.
