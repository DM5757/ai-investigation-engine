# Milestone 8 — Reviewer demo UI

**Deployed SHA:** `cbaa46b5a8e815f3435a895ed4fe454449ef4c6d`  
**Live:** https://ai-investigation-engine-scyz.onrender.com  
**CI:** https://github.com/DM5757/ai-investigation-engine/actions/runs/41434869265 (success)  
**Tag preserved:** `submission-2026-10-29`

## UI changes

- Investigate tab: sample chips, question/answer/status, citation chips → scroll-to-source, conflicts, steps + elapsed wall time, progress bar with elapsed seconds, humanized quota/timeout errors.
- Corpus tab: ACTIVE / chunk / collection metric cards from live `/api/stats`.
- Evaluation tab: held-out retrieval + M7 answer metrics with denominators, synthesis-mode notes, and explicit limitations (`/api/eval/runs` ← `app/data/published_eval.json`).
- Status legend; skip link; reduced-motion CSS; `textContent`-only rendering for answer/source text.

## Sample investigation questions (live API only)

| Category | Question |
| --- | --- |
| Factual | What is Roanoke–Blacksburg Regional Airport, and where is it located? |
| Multi-doc comparison | Is Ohio State University or California State University, Dominguez Hills further west? |
| Multi-hop | Michael Lent … Ice Road Truckers … premiered on what date? |
| Conflicting | auth-gateway deploy time on 2024-03-12 — note contradictions |
| Insufficient | What was FraudScorer CPU usage during the incident? |

## Production sample results @ `cbaa46b`

Evidence: `docs/evidence/m8_sample_smoke.json` / `.md` (5 UI sample cases).  
Full suite: `docs/evidence/prod_smoke_suite.json` — **10/10 PASS** (same SHA).  
HTML snapshot: `docs/evidence/m8_live_index.html`.

| Case | Status | ms | cites | Verdict |
| --- | ---: | ---: | ---: | --- |
| airport | answered | 11484 | 1 | PASS |
| multihop_ohio_csudh | answered | 10893 | 2 | PASS |
| multihop_lent_irt | answered | 9590 | 2 | PASS |
| contradiction_deploy | conflicting | 3395 | 2 | PASS |
| unanswerable_fraudscorer | insufficient | 3853 | 0 | PASS |

All five sample cases used **0 LLM calls** on this run. Full suite warm latencies typically **3–11 s**.

## Accessibility / security checks

- Skip link present; focus-visible outlines; `aria-live` on status/progress; contrast via dark-on-cream palette.
- Admin token memory-only (no `localStorage.setItem`).
- Security headers still: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, no CORS wildcard (integration test).
- Answer/source text via `textContent` (no HTML injection from corpus).

## Performance observations

- Warm sample investigations ~3–12 s wall clock on Render Free.
- Cold start can still add ~30–60 s before first response (progress UI surfaces elapsed time).

## Evaluation presentation

`/api/eval/runs` reports retrieval R@10 / MRR with n_scored=91/94 and M7 adaptive token F1 **0.183**, cite F1 **0.365**, abstention/contradiction **1.0** on 62 test questions — with limitations stating smoke success ≠ overall accuracy.

## Tests

Local: **193** passed (`pytest -m "not live"`), Ruff + mypy clean. CI green on `cbaa46b`.

## Remaining limitations

- Held-out token F1 still 0.183; EM ~0; multi-hop recall beyond demos remains imperfect.
- Free-tier LLM quota can still yield `llm_unavailable` on adaptive paths.
- Render Free cold starts remain.
