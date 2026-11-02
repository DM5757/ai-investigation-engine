# Production smoke suite results

- Created: `2026-11-02T08:56:25.120908+00:00`
- Base: `https://ai-investigation-engine-scyz.onrender.com`
- Deploy: `283bfc326aecb1c89d2b7da976bf58e31a3bdb61`
- Stats ACTIVE: `55081`
- Cases pass: **7** / honest_degraded: **0** / fail: **0**

| ID | Category | Status | ms | calls | cites | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `airport` | factual | answered | 11307.7 | 0 | 1 | PASS |
| `multihop_ohio_csudh` | entity_relationship_multihop | answered | 10785.9 | 0 | 2 | PASS |
| `multihop_lent_irt` | entity_relationship_multihop | answered | 10988.7 | 0 | 2 | PASS |
| `multihop_robinson_perdita` | entity_relationship_multihop | answered | 8790.2 | 0 | 2 | PASS |
| `colony_regression` | insufficient_missing_entity | insufficient | 2868.1 | 0 | 0 | PASS |
| `contradiction_deploy` | contradiction | conflicting | 3438.8 | 0 | 2 | PASS |
| `unanswerable_fraudscorer` | unanswerable | insufficient | 4454.0 | 0 | 0 | PASS |

## airport

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: Concise factual answer about Woodrum Field near Roanoke, VA.
- Status: `answered` degraded=False
- Duration: 11307.7 ms
- Usage: calls=0 tokens=0
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Roanoke–Blacksburg Regional Airport (IATA: ROA,\xa0ICAO: KROA,\xa0FAA LID: ROA) , also known as Woodrum Field, is a regional airport located three\xa0nautical miles (6\xa0km) northwest of the central business district of Roanoke, a city in Roanoke Coun [S1].'

## multihop_ohio_csudh

- Question: Is Ohio State University or California State University, Dominguez Hills further west?
- Expected: HotpotQA multi-hop; both gold titles verified ACTIVE in Neon.
- Status: `answered` degraded=False
- Duration: 10785.9 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Ohio State University', 'California State University, Dominguez Hills']
- Reasons: []
- Answer preview: 'Ohio State University: The Ohio State University, commonly referred to as Ohio State or OSU, is a large, primarily residential, public university in Columbus, Ohio. [S1] California State University, Dominguez Hills: It is located in the city of Carson, California in the South Bay region of Los Angeles County and was founded in 1960. [S2] Therefore California State University, Dominguez Hills is further west [S1, S2].'

## multihop_lent_irt

- Question: Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star on a reality television series that premiered on what date?
- Expected: HotpotQA multi-hop across writer + TV series premiere date.
- Status: `answered` degraded=False
- Duration: 10988.7 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Michael Lent (writer and producer)', 'Ice Road Truckers']
- Reasons: []
- Answer preview: 'Michael Lent is a mixed media writer and producer based in Los Angeles. [S1] Ice Road Truckers (commercially abbreviated IRT) is a reality television series that premiered on History, on June 17, 2007. [S2]'

## multihop_robinson_perdita

- Question: The character for whom Mary Robinson was nicknamed was the daughter of Leontes, king of which country?
- Expected: HotpotQA multi-hop nickname → Shakespeare character → country.
- Status: `answered` degraded=False
- Duration: 8790.2 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Mary Robinson (poet)', "Perdita (The Winter's Tale)"]
- Reasons: []
- Answer preview: 'During her lifetime she was known as "the English Sappho". [S1] She is the daughter of Leontes, King of Sicilia, and his wife Hermione. [S2]'

## colony_regression

- Question: Which evidence connects the investigation of the Roanoke colony disappearance to the key individuals involved, and what conclusions can be drawn from the available documents?
- Expected: Roanoke Colony title absent from ACTIVE corpus; must abstain.
- Status: `insufficient` degraded=False
- Duration: 2868.1 ms
- Usage: calls=0 tokens=0
- Citations (0): []
- Reasons: []
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'

## contradiction_deploy

- Question: What do the documents say about auth-gateway deploy time on 2024-03-12? Note any contradictions.
- Expected: Synthetic planted conflict: 08:10 UTC vs 14:00 UTC.
- Status: `conflicting` degraded=False
- Duration: 3438.8 ms
- Usage: calls=0 tokens=0
- Citations (2): ['Change Log March', 'Incident Report — Payment Outage March']
- Reasons: []
- Answer preview: 'Sources conflict:\n- deploy/deploy_time: 14:00 UTC [S1]\n- deploy/deploy_time: 08:10 UTC [S2]'

## unanswerable_fraudscorer

- Question: What was FraudScorer CPU usage during the incident?
- Expected: Evidence intentionally absent in synthetic corpus.
- Status: `insufficient` degraded=False
- Duration: 4454.0 ms
- Usage: calls=0 tokens=0
- Citations (0): []
- Reasons: []
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'
