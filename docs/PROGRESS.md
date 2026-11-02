# Progress

## Phase 0 — Complete

Render Free + Neon + Qdrant. Northflank rejected (payment card required).

## Phase 1 — Complete (2026-10-29)

- Local quality + 512 MB container bench (peak **284.6 MiB**)
- Public URL: https://ai-investigation-engine-scyz.onrender.com
- Evidence: `docs/evidence/phase1.txt`, `docs/evidence/phase1_deploy.txt`

## Phase 2 — Complete (2026-10-29)

Parsing, chunking, duplicates, document lifecycle (DOC-1 to DOC-5).

## Phase 3 — Complete (2026-10-29)

Hybrid retrieval (VEC-1 to VEC-4).

## Phase 4 — Complete (2026-10-29)

LLM gateway + investigation engine (RAG-1 to RAG-8).

## Phase 5 — Complete (2026-10-29)

Ask API + vanilla JS UI.

## Hotfix — Neon / Psycopg 3 (2026-10-29)

Normalize `postgresql://` → `postgresql+psycopg://`.

## Phase 6 — Complete (2026-10-29 evening) — DATA-1 ≥50k verified

- Measured 2026-10-30: ACTIVE **55,081**, FAILED **0**, Qdrant **56,890**, `meets_data1_50k: true`
- Chunk gap explained: total chunk_rows 56,900 = ACTIVE 56,890 + DELETED-doc rows 10
- Evidence: `docs/evidence/dataset_counts.json`, `docs/evidence/bulk_ingest.json`
- Live `/api/stats` on Render reconfirmed ACTIVE **55,081** (2026-10-30)

## Phase 7 — Evaluation

- Full-corpus retrieval `full55k_retrieval_v1`: n_scored=91; dense R@10 0.890; hybrid MRR 0.919
- Controlled answer `full55k_answer_v1` (n=12): investigation provider-limited mid-run
- Report: `docs/EVALUATION_REPORT.md`

## Post-submission quality — Complete (2026-10-30)

- Per-request LLM budget reset; budget/provider failure → explicit `llm_unavailable` (no fake partial essays)
- Question-conditioned sufficiency + claim filtering; colony abstention verified scripted
- Relative retrieval floor, phrase-aware rerank, citation prune-to-answer
- `/api/version` includes `git_commit` (Render verified `0f6adc3…`)
- Default wall-clock budget raised **120→300s** for Render Free latency
- Early tag `submission-2026-10-29` @ `1ab164d` **unchanged**

## Portfolio quality — docs + production smoke (2026-10-30)

- Public docs cleaned of candidate/interview handoff language (`c03b155`).
- Production smoke suite: `scripts/prod_smoke_suite.py` → `docs/evidence/prod_smoke_suite.json`.
- Live @ `c03b155`: airport **answered** (Woodrum Field, 1 cite, ~142s); budget isolation **pass**; several later cases **llm_unavailable**/client timeout under free-tier provider pressure.
- Quality deploy `04153fe` (CI green; Render `/api/version` matched): keyword-hint corpus preference, mixed-case focus phrases, degraded preview focus filter, evidence-preview title enrichment, retry wall-clock gate.
- Post-fix retest under exhausted providers: colony preview cites **0** (was 5 unrelated); payment degraded previews show correct titled synthetic docs; all three retested cases honest `llm_unavailable` (no hard fails).

## Milestone 3 — reliability / latency / provider resilience (2026-10-30)

- Deployed commits: `428ed09` (fail-fast + latency traces) then `fecabea` (retrieval wall-clock + smaller hybrid pools). Render `/api/version` matched.
- False near-zero `trace.latency_ms` fixed: stages wrap real work with `perf_counter`; request totals include stage breakdown.
- Provider failures classified (`daily_quota`, TPM/RPM, context overflow, auth); daily quota / context overflow are non-retryable; dead providers short-circuited within a request.
- Live acceptance @ `428ed09`: airport PASS ~75s; contradiction PASS; unanswerable PASS; multi-doc DEGRADED (`groq:daily_quota`); multihop answer quality FAIL; colony client timeout.
- Live retest @ `fecabea`: airport PASS ~67s (seed search ~12s, was ~65s); colony PASS `insufficient` @ ~48s with 0 cites.
- Tests: **163** passed (non-live). Early tag `submission-2026-10-29` unchanged.

## Milestone 4 — multi-hop reasoning / retrieval efficiency (2026-10-30)

- Root cause of OSU/CSUDH failure: hybrid retrieval already returned both gold titles; investigation lost the peer entity through campus-title drift, claim quotes that stopped at naming sentences (location lived in the anaphoric next sentence), and synthesizer hedging despite `answered` status.
- General fixes: per-entity comparison seeding + title-fidelity rerank; gated bridge-entity hops; anaphoric/relational heuristic claims; second-hop claims kept only when grounded in first-hop quotes; comparison-only dual-entity sufficiency; synthesizer hedge→deterministic fallback; embed/search caches and duplicate-search avoidance.
- Local multi-hop (Gemini after Groq daily quota): OSU/CSUDH **PASS** (2 cites, CSUDH further west); Lent→Ice Road Truckers premiere **PASS** (June 17, 2007); Robinson→Perdita/Sicilia **PASS**; colony abstention and airport factual preserved; contradiction deploy-time conflict recovered.
- Production @ `8964e79`: smoke **7/7 PASS** (airport ~14s; OSU/CSUDH ~14s with both gold cites; Lent ~22s; Robinson ~11s; colony insufficient; contradiction answered; unanswerable insufficient). CI green. Tag `submission-2026-10-29` unchanged.
- Tests: **175** passed (non-live).

## Milestone 5 — reliable investigation / eval / reviewer demos (2026-11-02)

- Deterministic plan + seed/bridge retrieval; skip LLM tool loop when seeded; prefer deterministic synthesis; skip conflict-adjudication LLM. Trace records `synthesis_mode` and `tools_llm_skipped`.
- Local demo set: **0 LLM calls**, typically **0.1–1.6s** per case (was multi-second with 3–5 provider calls).
- Answer eval `m5_answer_v2` on test split (**62** questions, ACTIVE 55081): investigation mean LLM calls **0.0**, mean latency **~0.82s**; abstention **0.5** vs baseline **0.0**; contradiction detection **0.5** vs baseline **0.0**. One Qdrant timeout recorded as error.
- Reviewer demo catalogue: `docs/evidence/reviewer_demo_cases.md`.
- Production @ `283bfc3`: smoke **7/7 PASS**, **0 LLM calls** each (airport ~11s; OSU/CSUDH ~11s; Lent ~11s; Robinson ~9s; colony ~3s; contradiction `conflicting` ~3s; unanswerable ~4s). CI green.
- Tests: **180** passed (non-live). Tag `submission-2026-10-29` unchanged.

## Milestone 6 — answer quality / adaptive synthesis (2026-11-02)

- Audited eval validity first (`docs/evidence/m6_eval_audit.md`); metrics unchanged; M5 results preserved.
- Span-oriented deterministic answers + adaptive LLM when confidence &lt; 0.7; question-gated conflicts; redacted-approver abstention.
- Held-out test (62, ACTIVE 55081): token F1 **0.031 → 0.080 (det) → 0.153 (adapt)**; abstention **0.5 → 1.0**; adaptive used **23** LLM / **39** det syntheses.
- Evidence: `docs/evidence/m6_report.md`, `eval/results/m6_test_*`.
- Production @ `a748661`: smoke **10/10 PASS**; adaptive LLM path confirmed on live multi-doc/unseen probes; curated demos remain green.
- Tests: **186** passed (non-live). CI green. Tag `submission-2026-10-29` unchanged.

## Milestone 7 — evidence accuracy / multi-hop coverage (2026-11-02)

- Audited M6 failures (`docs/evidence/m7_failure_audit.md`): 25 unnecessary abstentions, 1 missed causal contradiction, comparison entity extraction bugs.
- Fixes: soft technical claim support, causal root-cause conflicts, metric-attribute abstention, grounded premiere-date selection, longer relational quotes.
- Held-out test: token F1 **0.153 → 0.183**; cite F1 **0.309 → 0.365**; contradiction **0.50 → 1.00**; abstention stays **1.00**.
- Evidence: `docs/evidence/m7_report.md`, `eval/results/m7_test_adapt_v3__*`.
- Tests: **191** passed (non-live). Tag `submission-2026-10-29` unchanged.

## Outstanding technical follow-ups

1. Further Hotpot EM/alias normalization without gaming metrics.
2. Optional TPM-aware backoff under adaptive load.
3. UI sample-question chips once production demos stay green across deploys.
