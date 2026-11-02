# Production smoke suite results

- Created: `2026-11-02T10:19:16.944317+00:00`
- Base: `https://ai-investigation-engine-scyz.onrender.com`
- Deploy: `a748661d8f85a0b7e8d46e745c8afda808ac0af3`
- Stats ACTIVE: `55081`
- Cases pass: **10** / honest_degraded: **0** / fail: **0**

| ID | Category | Status | ms | calls | cites | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `airport` | factual | answered | 13950.7 | 0 | 1 | PASS |
| `multi_doc_payment` | multi_document | answered | 5352.7 | 1 | 2 | PASS |
| `multihop_ohio_csudh` | entity_relationship_multihop | answered | 10800.2 | 0 | 2 | PASS |
| `multihop_lent_irt` | entity_relationship_multihop | answered | 9699.4 | 0 | 2 | PASS |
| `multihop_robinson_perdita` | entity_relationship_multihop | answered | 8285.8 | 0 | 2 | PASS |
| `unanswerable_fraudscorer` | unanswerable | insufficient | 3860.5 | 0 | 0 | PASS |
| `contradiction_deploy` | contradiction | conflicting | 3360.1 | 0 | 2 | PASS |
| `colony_regression` | insufficient_missing_entity | insufficient | 3151.6 | 0 | 0 | PASS |
| `budget_isolation_1` | budget_isolation | answered | 4626.4 | 0 | 1 | PASS |
| `budget_isolation_2` | budget_isolation | answered | 6142.8 | 1 | 1 | PASS |

## airport

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: Concise factual answer about Woodrum Field near Roanoke, VA.
- Status: `answered` degraded=False
- Duration: 13950.7 ms
- Usage: calls=0 tokens=0
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Woodrum Field [S1].'

## multi_doc_payment

- Question: Which system changes caused disruptions in payment processing in March, which services were affected, and which documents support this?
- Expected: Requires combining synthetic incident + change-log style sources.
- Status: `answered` degraded=False
- Duration: 5352.7 ms
- Usage: calls=1 tokens=684
- Citations (2): ['Exec Summary', 'Incident Report — Payment Outage March']
- Reasons: []
- Answer preview: 'The March disruption was caused by an\u202fauth‑gateway\u202fchange, affecting the\u202fPaymentService; this is documented in the Exec Summary and the “Incident Report\u202f—\u202fPayment Outage March”\u202f[S1][S2].'

## multihop_ohio_csudh

- Question: Is Ohio State University or California State University, Dominguez Hills further west?
- Expected: HotpotQA multi-hop; both gold titles verified ACTIVE in Neon.
- Status: `answered` degraded=False
- Duration: 10800.2 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Ohio State University', 'California State University, Dominguez Hills']
- Reasons: []
- Answer preview: 'California State University, Dominguez Hills [S1, S2].'

## multihop_lent_irt

- Question: Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star on a reality television series that premiered on what date?
- Expected: HotpotQA multi-hop across writer + TV series premiere date.
- Status: `answered` degraded=False
- Duration: 9699.4 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Michael Lent (writer and producer)', 'Ice Road Truckers']
- Reasons: []
- Answer preview: 'June 17, 2007 [S1, S2].'

## multihop_robinson_perdita

- Question: The character for whom Mary Robinson was nicknamed was the daughter of Leontes, king of which country?
- Expected: HotpotQA multi-hop nickname → Shakespeare character → country.
- Status: `answered` degraded=False
- Duration: 8285.8 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Mary Robinson (poet)', "Perdita (The Winter's Tale)"]
- Reasons: []
- Answer preview: 'Sicilia [S1, S2].'

## unanswerable_fraudscorer

- Question: What was FraudScorer CPU usage during the incident?
- Expected: Evidence intentionally absent in synthetic corpus.
- Status: `insufficient` degraded=False
- Duration: 3860.5 ms
- Usage: calls=0 tokens=0
- Citations (0): []
- Reasons: []
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'

## contradiction_deploy

- Question: What do the documents say about auth-gateway deploy time on 2024-03-12? Note any contradictions.
- Expected: Synthetic planted conflict: 08:10 UTC vs 14:00 UTC.
- Status: `conflicting` degraded=False
- Duration: 3360.1 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Change Log March', 'Incident Report — Payment Outage March']
- Reasons: []
- Answer preview: 'Sources conflict:\n- authgateway/deploy_time: 14:00 UTC [S1]\n- authgateway/deploy_time: 08:10 UTC [S2]'

## colony_regression

- Question: Which evidence connects the investigation of the Roanoke colony disappearance to the key individuals involved, and what conclusions can be drawn from the available documents?
- Expected: Roanoke Colony title absent from ACTIVE corpus; must abstain.
- Status: `insufficient` degraded=False
- Duration: 3151.6 ms
- Usage: calls=0 tokens=0
- Citations (0): []
- Reasons: []
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'

## budget_isolation_1

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: First of two consecutive requests; budgets must reset per request.
- Status: `answered` degraded=False
- Duration: 4626.4 ms
- Usage: calls=0 tokens=0
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Woodrum Field [S1].'

## budget_isolation_2

- Question: Where are schools in the athletic association Cardinal Hayes High School is part of located?
- Expected: Second consecutive request. Pass isolation if this is not immediately budget-dead solely because F1 consumed a shared budget.
- Status: `answered` degraded=False
- Duration: 6142.8 ms
- Usage: calls=1 tokens=908
- Citations (1): ['Cardinal Hayes High School']
- Reasons: []
- Answer preview: 'Bronx, New\u202fCity, New\u202fYork\u202fState\u202f[\u200bS1]'
