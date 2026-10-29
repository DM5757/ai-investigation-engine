# Requirements traceability

Seeded in Phase 0 from the official assignment and master checklist. Status values: `Not started` | `Partial` | `Done-verified` | `Not verified` | `Missing`.

| ID | Requirement (spec section) | Implementation location | Test / verification | Status | Known limitation |
| --- | --- | --- | --- | --- | --- |
| DOC-1 | ≥3 file formats (target 6+: TXT, MD, PDF, DOCX, HTML, JSONL; CSV optional) | `app/ingestion/parsers/` | `tests/unit/test_parsers.py` | Done-verified | 7 formats; fixtures under `tests/fixtures/docs/` |
| DOC-2 | Extract text and important metadata | parsers + `metadata.py` | parser unit tests | Done-verified | Title/date/author where format provides them |
| DOC-3 | Chunking | `fixed_window` + `structure_aware` | `tests/unit/test_chunking.py` | Done-verified | Property tests; DOC-6 experiment later |
| DOC-4 | Handle duplicate information | `dedup/hashing.py`, `simhash.py` | `test_simhash` + lifecycle | Done-verified | Exact skip; near-dup flag/skip policy |
| DOC-5 | Add, update, delete documents | `lifecycle.py` + repos + reconcile | `tests/integration/test_lifecycle.py` | Done-verified | Crash hooks + reconcile covered |
| DOC-6 | Compare ≥2 chunking strategies (real experiment) | `scripts/chunking_experiment.py` | `eval/results/chunking_comparison.json` | Done-verified | Winner `fixed_window` (tied Recall@5, fewer chunks); default prod strategy remains `structure_aware` |
| DOC-7 | Justify processing architecture | `docs/DESIGN_DECISIONS.md`, DATABASE_DESIGN | Docs | Partial | Phase 2 schema notes added |
| VEC-1 | Vector database | `app/index/qdrant_store.py` (+ search) | `test_qdrant_store.py` isinstance + lifecycle | Done-verified | Embedded `:memory:` upsert/search verified; **Qdrant Cloud remote not smoked** |
| VEC-2 | Real embeddings and semantic search | `FastEmbedProvider` bge-small | dense-rescue integration + Phase 1 RSS | Done-verified | Real FastEmbed in Phase 3 tests; Render startup still gated by `EMBEDDING_ENABLED_AT_STARTUP` |
| VEC-3 | Hybrid search | `app/retrieval/hybrid.py` + BM25 sparse | sparse/dense rescue + fusion unit tests | Done-verified | Modes: dense/sparse/hybrid_rrf/hybrid_weighted/hybrid_rerank |
| VEC-4 | ≥1 custom search/ranking component | custom BM25 + custom reranker | `test_bm25` / `test_reranker` hand checks | Done-verified | Explainable linear features + MMR / near-dup / per-doc cap |
| RAG-1 | ≥1 LLM; RAG architecture | `app/llm/gateway.py` + `InvestigationEngine` | scripted + `phase4_live_trace.json` | Done-verified | Live Groq multi-doc answered 2026-10-29 |
| RAG-2 | Combine info from different documents | engine + aggregator + synthesizer | live citations live_a+live_b | Done-verified | Live trace cites ≥2 docs |
| RAG-3 | Multi-step complex questions | planner + tool loop | live plan n=2 + 4 tool rounds | Done-verified | Live plan type=causal; tools used |
| RAG-4 | Evidence-based answers; citations | synthesizer + verifier + quote check | live verify ok=True | Done-verified | Quotes match chunks; fabricated path unit-tested |
| RAG-5 | Detect contradictory information | `contradictions.py` | unit + scripted + `behavioral_rag_smoke.json` | Partial | Deterministic gates pass; live investigation still returns `answered` on planted conflicts |
| RAG-6 | Abstain when insufficient | `sufficiency.py` | unit + scripted + behavioral smoke | Partial | Deterministic empty→insufficient; live unanswerable still often `answered`/`partial` |
| RAG-7 | Handle LLM errors/limits | gateway retry/fallback/budget + degraded | `test_gateway` + eval stop-on-429 | Partial | Live Groq TPD exhaustion observed; Gemini thought_signature round-trip fixed |
| RAG-8 | Tool-calling / structured tools | `investigation/tools.py` | live tool rounds + schemas | Done-verified | Live tools_round_0..3 with tool calls |

| EVAL-1 | Automated evaluation harness | `eval/run_eval.py`, `eval/metrics.py` | `tests/unit/test_eval_metrics.py` + result JSONs | Done-verified | Resumable; `--scorable-only` + exclusion reasons |
| EVAL-2 | ≥40 questions across required types | `eval/questions/eval_set.json` (57 active-gold) | type_counts + `--require-active` | Done-verified | Hotpot titles must be ACTIVE; synthetic for contra/unans |
| EVAL-3 | Quantitative retrieval + answer metrics | `eval/metrics.py` + runners | `active_retrieval_v1` (n_scored=54), `active_investigation_v2` (partial) | Done-verified | Transparent denominators; 27/37 investigation rows provider-limited |
| EVAL-4 | Compare ≥2 configurations | dense vs hybrid; baseline vs investigation | comparison JSONs | Done-verified | DOC-6 chunking also compared |
| EVAL-5 | Error analysis | `docs/EVALUATION_REPORT.md` | report §§1,4,5 | Done-verified | Documents unresolved-gold root cause + budget bug |
| APP-1 | Python backend | FastAPI routes + deps (`documents`/`query`/`stats`) | `test_api_*` + phase5.txt | Done-verified | Thin handlers → lifecycle/engine |
| APP-2 | Functional UI (docs, ask, sources) | `app/ui/static/` | `test_api_ui_static` + phase5_ui_checklist | Done-verified | textContent-only; admin token in JS memory |
| DATA-1 | Process ≥50,000 documents/records | HotpotQA corpus + lifecycle ingest | `verify_counts.py` / `dataset_counts.json` | Partial | 55k corpus built; ACTIVE climbing after FAILED repair (~5k+ measured); claim 50k only when measured |
| DATA-2 | Cross-document retrieval; identifiable sources | `hotpotqa:<title>` external_key + citations | pilot/bulk + Phase 4 citations | Partial | Sources keyed; full-corpus retrieval eval is Phase 7 |
| DATA-3 | Incomplete and contradictory information | `data/manifests/synthetic_truth.json` | synthetic generator | Done-verified | Planted contradictions, incompleteness, injection samples |
| DATA-4 | Reproducible evaluation / subset justification | `docs/DATASET.md` + manifests | manifests sha256/seed | Done-verified | Seed 42; subset/scale justified in DATASET.md + storage estimate |
| DEP-1 | Public URL on free hosting | Render Free | `docs/evidence/phase1_deploy.txt` | Done-verified | Live: https://ai-investigation-engine-scyz.onrender.com (2026-10-29) |
| DEP-2 | Hosting and DB integration | Neon + app ready | `docs/evidence/prod_e2e_smoke.json` | Done-verified | Render ready + upload/query/update/delete/401 E2E 2026-10-29 |
| DEP-3 | Data persists across restarts | external Neon/Qdrant | restart test | Partial | Architecture chosen for persistence; local tests use temp SQLite + memory store |
| DEP-4 | Secrets protected | env/secrets; admin token; no CORS `*` | secret scan + UI | Partial | `.env` gitignored; admin token not stored in localStorage; keys never returned in API |
| DEP-5 | Deployment architecture, costs, free-tier limits documented | `FREE_TIER_NOTES.md`, DEPLOYMENT | docs | Partial | Phase 0 notes written; Deploy smoke pending |
| TECH-1 | Clean modular code, SoC, errors | `app/` layout | review/tests | Partial | API → services → repos; modules kept thin |
| TECH-2 | Automated tests; DB/API integration | `tests/` | local pytest 119 passed | Partial | Phase 5 API/UI covered; Render E2E for new routes pending |
| TECH-3 | Secure env config; technical docs | config + docs | TBD | Partial | Phase 0–1 docs started |
| TECH-4 | Performance and LLM cost understanding | PERFORMANCE_AND_COST | measured | Partial | Embed RSS/512m bench recorded; LLM cost TBD |
| SUB-1 | GitHub repo with history | git | `origin/main` + tag `submission-2026-10-29` | Partial | Early tag preserved; continuation commits on main |
| SUB-2 | Live demo link | README | `phase1_deploy.txt` | Done-verified | https://ai-investigation-engine-scyz.onrender.com |
| SUB-3 | README | README.md | review | Done-verified | Describes implemented system + honesty rules |
| SUB-4 | Evaluation report | `docs/EVALUATION_REPORT.md` | evidence paths | Done-verified | Preliminary metrics; owner should re-read |
| SUB-5 | AI usage report | `docs/AI_USAGE_REPORT.md` | owner fill-in | Partial | AI disclosure written; **candidate must complete independent-verification section** |
| INT-1 | Interview/docs/exercises | guides + drills | TBD | Not started | — |
