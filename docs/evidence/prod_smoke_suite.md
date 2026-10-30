# Production smoke suite results

- Created: `2026-10-30T06:24:45.630723+00:00`
- Base: `https://ai-investigation-engine-scyz.onrender.com`
- Deploy: `3738d2daa1e1fbb62f32d6082cc40c34ba3e83f7`
- Stats ACTIVE: `55081`
- Cases pass: **2** / honest_degraded: **0** / fail: **4**

| ID | Category | Status | ms | calls | cites | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `airport` | factual | answered | 15286.8 | 3 | 1 | PASS |
| `multihop_ohio_csudh` | entity_relationship_multihop | answered | 13201.0 | 3 | 2 | PASS |
| `multihop_lent_irt` | entity_relationship_multihop | answered | 14079.5 | 3 | 1 | FAIL |
| `multihop_robinson_perdita` | entity_relationship_multihop | answered | 12050.4 | 4 | 1 | FAIL |
| `colony_regression` | insufficient_missing_entity | answered | 38245.7 | 6 | 1 | FAIL |
| `contradiction_deploy` | contradiction | insufficient | 19003.3 | 3 | 0 | FAIL |

## airport

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: Concise factual answer about Woodrum Field near Roanoke, VA.
- Status: `answered` degraded=False
- Duration: 15286.8 ms
- Usage: calls=3 tokens=3895
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Roanoke–Blacksburg Regional Airport (also known as Woodrum Field) is a regional airport located three nautical miles (6 km) northwest of the central business district of Roanoke, a city in Roanoke County [S1].'

## multihop_ohio_csudh

- Question: Is Ohio State University or California State University, Dominguez Hills further west?
- Expected: HotpotQA multi-hop; both gold titles verified ACTIVE in Neon.
- Status: `answered` degraded=False
- Duration: 13201.0 ms
- Usage: calls=3 tokens=10204
- Citations (2): ['Ohio State University', 'California State University, Dominguez Hills']
- Reasons: []
- Answer preview: 'The provided claims are insufficient to determine whether Ohio State University or California State University, Dominguez Hills is further west, as they do not provide the geographical coordinates or locations for California State University, Dominguez Hills (only noting that it is part of the California State University system [S6], while Ohio State University is located in Columbus, Ohio [S1]).'

## multihop_lent_irt

- Question: Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star on a reality television series that premiered on what date?
- Expected: HotpotQA multi-hop across writer + TV series premiere date.
- Status: `answered` degraded=False
- Duration: 14079.5 ms
- Usage: calls=3 tokens=7953
- Citations (1): ['Michael Lent (writer and producer)']
- Reasons: ['answer_missing_required_tokens', 'too_few_distinct_docs:1<2']
- Answer preview: 'Based on the provided claims, Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, who is a star of the series *Ice Road Truckers* [S2]. However, the provided claims do not contain information regarding the premiere date of that reality television series.'

## multihop_robinson_perdita

- Question: The character for whom Mary Robinson was nicknamed was the daughter of Leontes, king of which country?
- Expected: HotpotQA multi-hop nickname → Shakespeare character → country.
- Status: `answered` degraded=False
- Duration: 12050.4 ms
- Usage: calls=4 tokens=8999
- Citations (1): ['Mary Robinson (poet)']
- Reasons: ['answer_missing_required_tokens']
- Answer preview: 'The provided claims are insufficient to answer the question about the character Mary Robinson was nicknamed for or the country of Leontes [S1].'

## colony_regression

- Question: Which evidence connects the investigation of the Roanoke colony disappearance to the key individuals involved, and what conclusions can be drawn from the available documents?
- Expected: Roanoke Colony title absent from ACTIVE corpus; must abstain.
- Status: `answered` degraded=False
- Duration: 38245.7 ms
- Usage: calls=6 tokens=23996
- Citations (1): ['Anecdotal evidence']
- Reasons: ['unexpected_status:answered']
- Answer preview: 'Based on the provided claims, there is no information or evidence connecting the investigation of the Roanoke colony disappearance to key individuals or documents. The provided sources only discuss the definition and limitations of anecdotal evidence [S1, S2, S3].'

## contradiction_deploy

- Question: What do the documents say about auth-gateway deploy time on 2024-03-12? Note any contradictions.
- Expected: Synthetic planted conflict: 08:10 UTC vs 14:00 UTC.
- Status: `insufficient` degraded=False
- Duration: 19003.3 ms
- Usage: calls=3 tokens=8445
- Citations (0): []
- Reasons: ['unexpected_status:insufficient']
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'
