# Production smoke suite results

- Created: `2026-11-02T11:01:15.677759+00:00`
- Base: `https://ai-investigation-engine-scyz.onrender.com`
- Deploy: `611b0d438dbbad91149d10c090ca312f0d470782`
- Stats ACTIVE: `55081`
- Cases pass: **10** / honest_degraded: **0** / fail: **0**

| ID | Category | Status | ms | calls | cites | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `airport` | factual | answered | 11971.9 | 0 | 1 | PASS |
| `multi_doc_payment` | multi_document | answered | 3484.6 | 0 | 2 | PASS |
| `multihop_ohio_csudh` | entity_relationship_multihop | answered | 10493.5 | 0 | 2 | PASS |
| `multihop_lent_irt` | entity_relationship_multihop | answered | 8683.7 | 0 | 2 | PASS |
| `multihop_robinson_perdita` | entity_relationship_multihop | answered | 9096.1 | 0 | 2 | PASS |
| `unanswerable_fraudscorer` | unanswerable | insufficient | 4262.5 | 0 | 0 | PASS |
| `contradiction_deploy` | contradiction | conflicting | 3637.2 | 0 | 2 | PASS |
| `colony_regression` | insufficient_missing_entity | insufficient | 2866.7 | 0 | 0 | PASS |
| `budget_isolation_1` | budget_isolation | answered | 5038.0 | 0 | 1 | PASS |
| `budget_isolation_2` | budget_isolation | answered | 4791.0 | 0 | 1 | PASS |

## airport

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: Concise factual answer about Woodrum Field near Roanoke, VA.
- Status: `answered` degraded=False
- Duration: 11971.9 ms
- Usage: calls=0 tokens=0
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Woodrum Field [S1].'

## multi_doc_payment

- Question: Which system changes caused disruptions in payment processing in March, which services were affected, and which documents support this?
- Expected: Requires combining synthetic incident + change-log style sources.
- Status: `answered` degraded=False
- Duration: 3484.6 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Exec Summary', 'Incident Report — Payment Outage March']
- Reasons: []
- Answer preview: 'payment and authentication services [S1, S2].'

## multihop_ohio_csudh

- Question: Is Ohio State University or California State University, Dominguez Hills further west?
- Expected: HotpotQA multi-hop; both gold titles verified ACTIVE in Neon.
- Status: `answered` degraded=False
- Duration: 10493.5 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Ohio State University', 'California State University, Dominguez Hills']
- Reasons: []
- Answer preview: 'California State University, Dominguez Hills [S1, S2].'

## multihop_lent_irt

- Question: Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star on a reality television series that premiered on what date?
- Expected: HotpotQA multi-hop across writer + TV series premiere date.
- Status: `answered` degraded=False
- Duration: 8683.7 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Michael Lent (writer and producer)', 'Ice Road Truckers']
- Reasons: []
- Answer preview: 'June 17, 2007 [S1, S2].'

## multihop_robinson_perdita

- Question: The character for whom Mary Robinson was nicknamed was the daughter of Leontes, king of which country?
- Expected: HotpotQA multi-hop nickname → Shakespeare character → country.
- Status: `answered` degraded=False
- Duration: 9096.1 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Mary Robinson (poet)', "Perdita (The Winter's Tale)"]
- Reasons: []
- Answer preview: 'Sicilia [S1, S2].'

## unanswerable_fraudscorer

- Question: What was FraudScorer CPU usage during the incident?
- Expected: Evidence intentionally absent in synthetic corpus.
- Status: `insufficient` degraded=False
- Duration: 4262.5 ms
- Usage: calls=0 tokens=0
- Citations (0): []
- Reasons: []
- Answer preview: 'The asked measurement or attribute is not present in the retrieved evidence.'

## contradiction_deploy

- Question: What do the documents say about auth-gateway deploy time on 2024-03-12? Note any contradictions.
- Expected: Synthetic planted conflict: 08:10 UTC vs 14:00 UTC.
- Status: `conflicting` degraded=False
- Duration: 3637.2 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Change Log March', 'Incident Report — Payment Outage March']
- Reasons: []
- Answer preview: 'Sources conflict:\n- 20240312/deploy_time: 14:00 UTC [S1]\n- 20240312/deploy_time: 08:10 UTC [S2]'

## colony_regression

- Question: Which evidence connects the investigation of the Roanoke colony disappearance to the key individuals involved, and what conclusions can be drawn from the available documents?
- Expected: Roanoke Colony title absent from ACTIVE corpus; must abstain.
- Status: `insufficient` degraded=False
- Duration: 2866.7 ms
- Usage: calls=0 tokens=0
- Citations (0): []
- Reasons: []
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'

## budget_isolation_1

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: First of two consecutive requests; budgets must reset per request.
- Status: `answered` degraded=False
- Duration: 5038.0 ms
- Usage: calls=0 tokens=0
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Woodrum Field [S1].'

## budget_isolation_2

- Question: Where are schools in the athletic association Cardinal Hayes High School is part of located?
- Expected: Second consecutive request. Pass isolation if this is not immediately budget-dead solely because F1 consumed a shared budget.
- Status: `answered` degraded=False
- Duration: 4791.0 ms
- Usage: calls=0 tokens=0
- Citations (1): ['Blanchard Valley Conference']
- Reasons: []
- Answer preview: 'Hancock, Putnam, Seneca [S1].'
