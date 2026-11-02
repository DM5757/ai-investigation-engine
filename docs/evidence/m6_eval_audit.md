# Milestone 6 — Evaluation validity audit

Preserved baseline: `eval/results/m5_answer_v2__full_investigation.json` (do not overwrite).

## Metric definitions (unchanged)

| Metric | Definition | Granularity |
| --- | --- | --- |
| Exact match | Hotpot-style normalize (lower, strip punct, collapse space) equality | Full answer string |
| Token F1 | Bag-of-tokens precision/recall F1 after same normalize | Tokens |
| Citation P/R/F1 | Cited **document ids** vs gold supporting **document ids** | Document (not chunk/fact) |
| Abstention | `status == insufficient` on `question_type=unanswerable` | Status only |
| Contradiction | `status == conflicting` **or** `conflicts > 0` | Status / conflict count |

Denominators: answer metrics average over all scored answer rows (including insufficient → citation F1 often 0). Abstention/contradiction average only over those type subsets (n=2 each on test).

## Gold answers

Hotpot-style short spans: mean **16.6 chars / 2.7 tokens** on test (e.g. `ARY Films`, `June 17, 2007`, `Summer Holiday`).

## Root causes of low investigation token F1 (~0.03)

1. **Verbose quote dumps** — deterministic synthesis emits full wiki sentences; even when the gold span is present, precision collapses.
2. **Wrong claim selection** — gold span contained in prediction on only **~14%** of scorable items; many answers cite unrelated entities.
3. **Metric is valid** — Hotpot short-answer F1 correctly penalizes long unsupported text; do not loosen normalization.

Oracle: if we emitted the gold string whenever it appeared in the prediction, mean F1 would still be only ~0.14 (containment rate), confirming selection quality is the main gap beyond verbosity.

## Root causes of low citation F1 (~0.28)

1. Averaging includes **insufficient** rows (often 0 cites → F1 0). Answered-only citation F1 ≈ **0.40**.
2. Missing second gold docs on multi-hop / multi-doc items (recall).
3. Occasional wrong-doc cites (precision 0).

## Category notes (m5_answer_v2)

| Type | n | Mean token F1 | Notes |
| --- | ---: | ---: | --- |
| factual | 50 | 0.030 | Short gold vs long quotes / wrong docs |
| multi_hop | 3 | 0.130 | Better when bridge works; still verbose |
| contradiction | 2 | 0.0 | Special gold; status metric matters |
| unanswerable | 2 | 0.0 | 1/2 correct abstention (`syn_incomplete_inc1_approver` false-answered) |

## Conclusion

Improve **span-oriented synthesis + claim selection + adaptive LLM routing**; keep metric definitions. Report answered-only citation F1 as an additional diagnostic, not a replacement.

## Held-out before / after (test split, ACTIVE 55,081)

| Run | Token F1 | Citation F1 | Abstention | Notes |
| --- | ---: | ---: | ---: | --- |
| `m5_answer_v2` investigation | 0.031 | 0.279 | 0.50 | Verbose dumps; 0 LLM |
| `m6_test_det_v1` | 0.080 | 0.272 | **1.00** | Span-first deterministic |
| `m6_test_adapt_v1` | **0.153** | **0.309** | **1.00** | 23/62 LLM-assisted |

Full write-up: `docs/evidence/m6_report.md`.
