# Production smoke suite results

- Created: `2026-10-30T07:09:53.596134+00:00`
- Base: `https://ai-investigation-engine-scyz.onrender.com`
- Deploy: `8964e791f460e66190cea28d58c490e0efd69b06`
- Stats ACTIVE: `55081`
- Cases pass: **7** / honest_degraded: **0** / fail: **0**

| ID | Category | Status | ms | calls | cites | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `airport` | factual | answered | 13946.8 | 3 | 1 | PASS |
| `multihop_ohio_csudh` | entity_relationship_multihop | answered | 14019.9 | 3 | 2 | PASS |
| `multihop_lent_irt` | entity_relationship_multihop | answered | 21660.6 | 3 | 3 | PASS |
| `multihop_robinson_perdita` | entity_relationship_multihop | answered | 10724.7 | 3 | 2 | PASS |
| `colony_regression` | insufficient_missing_entity | insufficient | 41690.1 | 5 | 0 | PASS |
| `contradiction_deploy` | contradiction | answered | 46357.8 | 4 | 2 | PASS |
| `unanswerable_fraudscorer` | unanswerable | insufficient | 11838.1 | 5 | 0 | PASS |

## airport

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: Concise factual answer about Woodrum Field near Roanoke, VA.
- Status: `answered` degraded=False
- Duration: 13946.8 ms
- Usage: calls=3 tokens=2515
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Roanoke–Blacksburg Regional Airport (also known as Woodrum Field, with IATA code ROA, ICAO code KROA, and FAA LID: ROA) is a regional airport located three nautical miles (6 km) northwest of the central business district of Roanoke, a city in Roanoke County [S1].'

## multihop_ohio_csudh

- Question: Is Ohio State University or California State University, Dominguez Hills further west?
- Expected: HotpotQA multi-hop; both gold titles verified ACTIVE in Neon.
- Status: `answered` degraded=False
- Duration: 14019.9 ms
- Usage: calls=3 tokens=8109
- Citations (2): ['Ohio State University', 'California State University, Dominguez Hills']
- Reasons: []
- Answer preview: 'California State University, Dominguez Hills is located in Carson, California [S4], while Ohio State University is located in Columbus, Ohio [S1]. Because California is further west than Ohio, California State University, Dominguez Hills is further west.'

## multihop_lent_irt

- Question: Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star on a reality television series that premiered on what date?
- Expected: HotpotQA multi-hop across writer + TV series premiere date.
- Status: `answered` degraded=False
- Duration: 21660.6 ms
- Usage: calls=3 tokens=5418
- Citations (3): ['Ice Road Truckers', 'Michael Lent (writer and producer)', 'Michael Lent (writer and producer)']
- Reasons: []
- Answer preview: 'Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star of the reality television series *Ice Road Truckers*, which premiered on June 17, 2007 [S1, S3].'

## multihop_robinson_perdita

- Question: The character for whom Mary Robinson was nicknamed was the daughter of Leontes, king of which country?
- Expected: HotpotQA multi-hop nickname → Shakespeare character → country.
- Status: `answered` degraded=False
- Duration: 10724.7 ms
- Usage: calls=3 tokens=7627
- Citations (2): ["Perdita (The Winter's Tale)", 'Mary Robinson (poet)']
- Reasons: []
- Answer preview: 'Mary Robinson earned the nickname "Perdita" for playing the heroine Perdita in Shakespeare\'s *The Winter\'s Tale* [S3]. That character is the daughter of Leontes, the King of Sicilia [S1].'

## colony_regression

- Question: Which evidence connects the investigation of the Roanoke colony disappearance to the key individuals involved, and what conclusions can be drawn from the available documents?
- Expected: Roanoke Colony title absent from ACTIVE corpus; must abstain.
- Status: `insufficient` degraded=False
- Duration: 41690.1 ms
- Usage: calls=5 tokens=16626
- Citations (0): []
- Reasons: []
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'

## contradiction_deploy

- Question: What do the documents say about auth-gateway deploy time on 2024-03-12? Note any contradictions.
- Expected: Synthetic planted conflict: 08:10 UTC vs 14:00 UTC.
- Status: `answered` degraded=False
- Duration: 46357.8 ms
- Usage: calls=4 tokens=5683
- Citations (2): ['Incident Report — Payment Outage March', 'Change Log March']
- Reasons: []
- Answer preview: 'The documents contain a contradiction regarding the deploy time of the auth-gateway on 2024-03-12:\n\n* The Incident Report states that the auth-gateway deploy occurred at 08:10 UTC [S1].\n* The Change Log states that auth-gateway version 2.4.1 was deployed at 14:00 UTC [S2].'

## unanswerable_fraudscorer

- Question: What was FraudScorer CPU usage during the incident?
- Expected: Evidence intentionally absent in synthetic corpus.
- Status: `insufficient` degraded=False
- Duration: 11838.1 ms
- Usage: calls=5 tokens=25335
- Citations (0): []
- Reasons: []
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'
