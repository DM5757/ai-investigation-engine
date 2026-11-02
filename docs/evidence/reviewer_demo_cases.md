# Reviewer demo cases (verified)

Public demo: https://ai-investigation-engine-scyz.onrender.com

These questions are taken from the indexed HotpotQA + synthetic corpus. They are **not** hardcoded answers — they exercise the live investigation path.

| # | Category | Question | Expected behavior |
| --- | --- | --- | --- |
| 1 | Factual | What is Roanoke–Blacksburg Regional Airport, and where is it located? | `answered`; Woodrum Field / Roanoke, VA; cite airport doc |
| 2 | Multi-hop comparison | Is Ohio State University or California State University, Dominguez Hills further west? | `answered`; CSUDH further west; cite both gold titles |
| 3 | Multi-hop bridge | Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star on a reality television series that premiered on what date? | `answered`; June 17, 2007; cite Lent + Ice Road Truckers |
| 4 | Multi-hop bridge | The character for whom Mary Robinson was nicknamed was the daughter of Leontes, king of which country? | `answered`; Sicilia/Sicily; cite Robinson and/or Perdita |
| 5 | Contradiction | What do the documents say about auth-gateway deploy time on 2024-03-12? Note any contradictions. | `conflicting` (or answered naming both); 08:10 UTC vs 14:00 UTC |
| 6 | Abstention | Which evidence connects the investigation of the Roanoke colony disappearance to the key individuals involved, and what conclusions can be drawn from the available documents? | `insufficient`; 0 citations |
| 7 | Unanswerable | What was FraudScorer CPU usage during the incident? | `insufficient`; no fabricated CPU number |

Measured production outcomes are recorded in `docs/evidence/prod_smoke_suite.json` after each acceptance run.
