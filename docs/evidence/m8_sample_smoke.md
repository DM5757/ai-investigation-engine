# Production smoke suite results

- Created: `2026-11-02T11:14:10.716578+00:00`
- Base: `https://ai-investigation-engine-scyz.onrender.com`
- Deploy: `cbaa46b5a8e815f3435a895ed4fe454449ef4c6d`
- Stats ACTIVE: `55081`
- Cases pass: **5** / honest_degraded: **0** / fail: **0**

| ID | Category | Status | ms | calls | cites | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `airport` | factual | answered | 11483.8 | 0 | 1 | PASS |
| `multihop_ohio_csudh` | entity_relationship_multihop | answered | 10893.3 | 0 | 2 | PASS |
| `multihop_lent_irt` | entity_relationship_multihop | answered | 9589.7 | 0 | 2 | PASS |
| `contradiction_deploy` | contradiction | conflicting | 3394.5 | 0 | 2 | PASS |
| `unanswerable_fraudscorer` | unanswerable | insufficient | 3852.6 | 0 | 0 | PASS |

## airport

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: Concise factual answer about Woodrum Field near Roanoke, VA.
- Status: `answered` degraded=False
- Duration: 11483.8 ms
- Usage: calls=0 tokens=0
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Woodrum Field [S1].'

## multihop_ohio_csudh

- Question: Is Ohio State University or California State University, Dominguez Hills further west?
- Expected: HotpotQA multi-hop; both gold titles verified ACTIVE in Neon.
- Status: `answered` degraded=False
- Duration: 10893.3 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Ohio State University', 'California State University, Dominguez Hills']
- Reasons: []
- Answer preview: 'California State University, Dominguez Hills [S1, S2].'

## multihop_lent_irt

- Question: Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star on a reality television series that premiered on what date?
- Expected: HotpotQA multi-hop across writer + TV series premiere date.
- Status: `answered` degraded=False
- Duration: 9589.7 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Michael Lent (writer and producer)', 'Ice Road Truckers']
- Reasons: []
- Answer preview: 'June 17, 2007 [S1, S2].'

## contradiction_deploy

- Question: What do the documents say about auth-gateway deploy time on 2024-03-12? Note any contradictions.
- Expected: Synthetic planted conflict: 08:10 UTC vs 14:00 UTC.
- Status: `conflicting` degraded=False
- Duration: 3394.5 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Change Log March', 'Incident Report — Payment Outage March']
- Reasons: []
- Answer preview: 'Sources conflict:\n- 20240312/deploy_time: 14:00 UTC [S1]\n- 20240312/deploy_time: 08:10 UTC [S2]'

## unanswerable_fraudscorer

- Question: What was FraudScorer CPU usage during the incident?
- Expected: Evidence intentionally absent in synthetic corpus.
- Status: `insufficient` degraded=False
- Duration: 3852.6 ms
- Usage: calls=0 tokens=0
- Citations (0): []
- Reasons: []
- Answer preview: 'The asked measurement or attribute is not present in the retrieved evidence.'
