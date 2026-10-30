# Production smoke suite results

- Created: `2026-10-30T03:55:38.803332+00:00`
- Base: `https://ai-investigation-engine-scyz.onrender.com`
- Deploy: `c03b1557d3bb4ee766d1c1d7052177bd6ec6e8a3`
- Stats ACTIVE: `55081`
- Cases pass: **3** / honest_degraded: **2** / fail: **3**

| ID | Category | Status | ms | calls | cites | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `airport` | factual | answered | 142241.9 | 5 | 1 | PASS |
| `multi_doc_payment` | multi_document | insufficient | 221031.1 | 5 | 0 | FAIL |
| `multihop_ohio_csudh` | entity_relationship_multihop | None | 330369.3 | None | None | FAIL |
| `unanswerable_fraudscorer` | unanswerable | None | 330763.0 | None | None | FAIL |
| `contradiction_deploy` | contradiction | llm_unavailable | 295901.4 | 3 | 5 | DEGRADED |
| `colony_regression` | insufficient_missing_entity | llm_unavailable | 257399.9 | 2 | 5 | DEGRADED |
| `budget_isolation_1` | budget_isolation | llm_unavailable | 135791.9 | 2 | 2 | PASS |
| `budget_isolation_2` | budget_isolation | answered | 177829.1 | 4 | 1 | PASS |

## airport

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: Concise factual answer about Woodrum Field near Roanoke, VA.
- Status: `answered` degraded=False
- Duration: 142241.9 ms
- Usage: calls=5 tokens=None
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Roanoke–Blacksburg Regional Airport (IATA : ROA, ICAO : KROA, FAA LID : ROA), also called Woodrum Field, is a regional airport situated about three nautical miles (≈ 6 km) northwest of the central business district of Roanoke, Virginia【S1】.'

## multi_doc_payment

- Question: Which system changes caused disruptions in payment processing in March, which services were affected, and which documents support this?
- Expected: Requires combining synthetic incident + change-log style sources.
- Status: `insufficient` degraded=False
- Duration: 221031.1 ms
- Usage: calls=5 tokens=5705
- Citations (0): []
- Reasons: ['unexpected_status:insufficient']
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'

## multihop_ohio_csudh

- Question: Is Ohio State University or California State University, Dominguez Hills further west?
- Expected: HotpotQA multi-hop; both gold titles verified ACTIVE in Neon.
- Status: `None` degraded=None
- Duration: 330369.3 ms
- Usage: calls=None tokens=None
- Citations (None): None
- Reasons: ['request_failed_or_timeout']
- Answer preview: None

## unanswerable_fraudscorer

- Question: What was FraudScorer CPU usage during the incident?
- Expected: Evidence intentionally absent in synthetic corpus.
- Status: `None` degraded=None
- Duration: 330763.0 ms
- Usage: calls=None tokens=None
- Citations (None): None
- Reasons: ['request_failed_or_timeout']
- Answer preview: None

## contradiction_deploy

- Question: What do the documents say about auth-gateway deploy time on 2024-03-12? Note any contradictions.
- Expected: Synthetic planted conflict: 08:10 UTC vs 14:00 UTC.
- Status: `llm_unavailable` degraded=True
- Duration: 295901.4 ms
- Usage: calls=3 tokens=2401
- Citations (5): ['86fa752f-640d-4a79-8210-6481514cd144', 'de2106e6-6b42-4299-af93-b35c82be5532', 'a2993b11-e38e-4fa5-9cdd-a1e67b771acb', '137a5f79-3d05-4de3-926d-a9c53ebd3884', '86fa752f-640d-4a79-8210-6481514cd144']
- Reasons: ['provider_or_budget_degraded']
- Answer preview: ''

## colony_regression

- Question: Which evidence connects the investigation of the Roanoke colony disappearance to the key individuals involved, and what conclusions can be drawn from the available documents?
- Expected: Roanoke Colony title absent from ACTIVE corpus; must abstain.
- Status: `llm_unavailable` degraded=True
- Duration: 257399.9 ms
- Usage: calls=2 tokens=1200
- Citations (5): ['ec3643c8-d27d-414c-aa8b-47d97e7ea25e', '5fdece0a-a66b-4b7e-876d-3fa83e4e2574', '58b6f473-f828-445f-ba47-f4eb4ea445e1', 'a64a384f-c3d6-465e-9f41-f2c3670f718e', 'd7d05dcb-c7fd-407c-9786-db62bf4054bb']
- Reasons: ['provider_or_budget_degraded']
- Answer preview: ''

## budget_isolation_1

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: First of two consecutive requests; budgets must reset per request.
- Status: `llm_unavailable` degraded=True
- Duration: 135791.9 ms
- Usage: calls=2 tokens=949
- Citations (2): ['b16b4334-f9a7-4ced-99a5-d5f986d8c4ac', 'b16b4334-f9a7-4ced-99a5-d5f986d8c4ac']
- Reasons: []
- Answer preview: ''

## budget_isolation_2

- Question: Where are schools in the athletic association Cardinal Hayes High School is part of located?
- Expected: Second consecutive request. Pass isolation if this is not immediately budget-dead solely because F1 consumed a shared budget.
- Status: `answered` degraded=False
- Duration: 177829.1 ms
- Usage: calls=4 tokens=2877
- Citations (1): ['Cardinal Hayes High School']
- Reasons: []
- Answer preview: 'Based on the provided claims, there is no information regarding the athletic association that Cardinal Hayes High School is part of or the locations of the schools in that association [S1].'
