# Production smoke suite results

- Created: `2026-10-30T06:06:16.250046+00:00`
- Base: `https://ai-investigation-engine-scyz.onrender.com`
- Deploy: `464d8b20f6f9a368746747bc15b5146f822b3c89`
- Stats ACTIVE: `55081`
- Cases pass: **3** / honest_degraded: **0** / fail: **2**

| ID | Category | Status | ms | calls | cites | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `airport` | factual | answered | 10962.7 | 3 | 1 | PASS |
| `multihop_ohio_csudh` | entity_relationship_multihop | answered | 9765.5 | 3 | 2 | PASS |
| `multihop_lent_irt` | entity_relationship_multihop | answered | 12394.6 | 4 | 1 | FAIL |
| `multihop_robinson_perdita` | entity_relationship_multihop | answered | 8670.2 | 4 | 1 | FAIL |
| `colony_regression` | insufficient_missing_entity | insufficient | 25169.8 | 5 | 0 | PASS |

## airport

- Question: What is Roanoke–Blacksburg Regional Airport, and where is it located?
- Expected: Concise factual answer about Woodrum Field near Roanoke, VA.
- Status: `answered` degraded=False
- Duration: 10962.7 ms
- Usage: calls=3 tokens=2156
- Citations (1): ['Roanoke–Blacksburg Regional Airport']
- Reasons: []
- Answer preview: 'Roanoke–Blacksburg Regional Airport (IATA\u202f:\u202fROA, ICAO\u202f:\u202fKROA, FAA\u202fLID\u202f:\u202fROA), also called Woodrum Field, is a regional airport situated about three nautical miles (≈\u202f6\u202fkm) northwest of the central business district of Roanoke, Virginia【S1】.'

## multihop_ohio_csudh

- Question: Is Ohio State University or California State University, Dominguez Hills further west?
- Expected: HotpotQA multi-hop; both gold titles verified ACTIVE in Neon.
- Status: `answered` degraded=False
- Duration: 9765.5 ms
- Usage: calls=3 tokens=5874
- Citations (2): ['Ohio State University', 'StubHub Center']
- Reasons: []
- Answer preview: 'Based on the provided claims, the provided sources state that Ohio State University is located in Columbus, Ohio [S1], while California State University, Dominguez Hills is located on the West Coast in Carson, California [S9]. However, the provided claims are insufficient to directly determine which university is further west.'

## multihop_lent_irt

- Question: Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star on a reality television series that premiered on what date?
- Expected: HotpotQA multi-hop across writer + TV series premiere date.
- Status: `answered` degraded=False
- Duration: 12394.6 ms
- Usage: calls=4 tokens=9711
- Citations (1): ['Michael Lent (writer and producer)']
- Reasons: ['answer_missing_required_tokens', 'too_few_distinct_docs:1<2']
- Answer preview: 'Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star of the series *Ice Road Truckers* [S2]. The provided claims do not contain the premiere date of the television series.'

## multihop_robinson_perdita

- Question: The character for whom Mary Robinson was nicknamed was the daughter of Leontes, king of which country?
- Expected: HotpotQA multi-hop nickname → Shakespeare character → country.
- Status: `answered` degraded=False
- Duration: 8670.2 ms
- Usage: calls=4 tokens=4458
- Citations (1): ['Mary Robinson (poet)']
- Reasons: ['answer_missing_required_tokens']
- Answer preview: 'Based on the provided sources, there is insufficient information to answer the question about the character Mary Robinson was nicknamed for or the country of Leontes.'

## colony_regression

- Question: Which evidence connects the investigation of the Roanoke colony disappearance to the key individuals involved, and what conclusions can be drawn from the available documents?
- Expected: Roanoke Colony title absent from ACTIVE corpus; must abstain.
- Status: `insufficient` degraded=False
- Duration: 25169.8 ms
- Usage: calls=5 tokens=19087
- Citations (0): []
- Reasons: []
- Answer preview: 'No verified claims could be grounded in retrieved document quotes.'
