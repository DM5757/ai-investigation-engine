# Requirements traceability

Seeded in Phase 0 from the official assignment and master checklist. Status values: `Not started` | `Partial` | `Done-verified` | `Not verified` | `Missing`.

| ID | Requirement (spec section) | Implementation location | Test / verification | Status | Known limitation |
| --- | --- | --- | --- | --- | --- |
| DOC-1 | ≥3 file formats (target 6+: TXT, MD, PDF, DOCX, HTML, JSONL; CSV optional) | `app/ingestion/parsers/` | `tests/unit/test_parsers.py` | Done-verified | 7 formats; fixtures under `tests/fixtures/docs/` |
| DOC-2 | Extract text and important metadata | parsers + `metadata.py` | parser unit tests | Done-verified | Title/date/author where format provides them |
| DOC-3 | Chunking | `fixed_window` + `structure_aware` | `tests/unit/test_chunking.py` | Done-verified | Property tests; DOC-6 experiment later |
| DOC-4 | Handle duplicate information | `dedup/hashing.py`, `simhash.py` | `test_simhash` + lifecycle | Done-verified | Exact skip; near-dup flag/skip policy |
| DOC-5 | Add, update, delete documents | `lifecycle.py` + repos + reconcile | `tests/integration/test_lifecycle.py` | Done-verified | Crash hooks + reconcile covered |
| DOC-6 | Compare ≥2 chunking strategies (real experiment) | TBD `scripts/chunking_experiment.py` | TBD | Not started | Deferred to Phase 6 |
| DOC-7 | Justify processing architecture | `docs/DESIGN_DECISIONS.md`, DATABASE_DESIGN | Docs | Partial | Phase 2 schema notes added |
| VEC-1 | Vector database | `app/index/qdrant_store.py` | lifecycle integration | Partial | Store Protocol + Qdrant adapter; real embeddings Phase 3 |
| VEC-2 | Real embeddings and semantic search | `fastembed` bge-small (candidate) | local RSS bench | Partial | Local RSS OK (~268 MB); not finalized for Render |
| VEC-3 | Hybrid search | dense + custom sparse BM25 | TBD | Not started | — |
| VEC-4 | ≥1 custom search/ranking component | custom BM25 + custom reranker | TBD | Not started | — |
| RAG-1 | ≥1 LLM; RAG architecture | Groq primary, Gemini secondary | TBD | Partial | Model IDs revised (Llama free removed) |
| RAG-2 | Combine info from different documents | investigation engine | TBD | Not started | — |
| RAG-3 | Multi-step complex questions | planner + tools | TBD | Not started | — |
| RAG-4 | Evidence-based answers; citations | synthesizer + verifier | TBD | Not started | — |
| RAG-5 | Detect contradictory information | contradictions module | TBD | Not started | — |
| RAG-6 | Abstain when insufficient | sufficiency + abstention | TBD | Not started | — |
| RAG-7 | Handle LLM errors/limits | gateway retry/fallback/budget | TBD | Not started | — |
| RAG-8 | Tool-calling / structured tools | investigation tools | TBD | Not started | — |
| EVAL-1 | Automated evaluation harness | `eval/` | TBD | Not started | — |
| EVAL-2 | ≥40 questions across required types | `eval/questions/` | TBD | Not started | — |
| EVAL-3 | Quantitative retrieval + answer metrics | `eval/metrics.py` | TBD | Not started | — |
| EVAL-4 | Compare ≥2 configurations | `eval/configs/` | TBD | Not started | — |
| EVAL-5 | Error analysis | EVALUATION_REPORT | TBD | Not started | — |
| APP-1 | Python backend | FastAPI (`app/main.py`) | local health + pytest | Partial | Walking skeleton only |
| APP-2 | Functional UI (docs, ask, sources) | `app/ui/static/` | TBD | Not started | — |
| DATA-1 | Process ≥50,000 documents/records | HotpotQA + synthetic | count script | Not started | No assignment file attached; public HotpotQA planned |
| DATA-2 | Cross-document retrieval; identifiable sources | corpus + citations | TBD | Not started | — |
| DATA-3 | Incomplete and contradictory information | synthetic truth | TBD | Not started | — |
| DATA-4 | Reproducible evaluation / subset justification | DATASET.md + manifests | TBD | Not started | — |
| DEP-1 | Public URL on free hosting | Render Free | `docs/evidence/phase1_deploy.txt` | Done-verified | Live: https://ai-investigation-engine-scyz.onrender.com (2026-10-29) |
| DEP-2 | Hosting and DB integration | Neon + app ready | public `/api/health/ready` | Partial | DB ok on Render; Qdrant not configured yet |
| DEP-3 | Data persists across restarts | external Neon/Qdrant | restart test | Partial | Architecture chosen for persistence |
| DEP-4 | Secrets protected | env/secrets; `.gitignore` | secret scan | Partial | `.env` gitignored; CI scan TBD |
| DEP-5 | Deployment architecture, costs, free-tier limits documented | `FREE_TIER_NOTES.md`, DEPLOYMENT | docs | Partial | Phase 0 notes written; Deploy smoke pending |
| TECH-1 | Clean modular code, SoC, errors | `app/` layout | review/tests | Partial | Scaffold + health routes; full SoC later |
| TECH-2 | Automated tests; DB/API integration | `tests/` | local pytest 5 passed | Partial | CI present; live deploy tests pending |
| TECH-3 | Secure env config; technical docs | config + docs | TBD | Partial | Phase 0–1 docs started |
| TECH-4 | Performance and LLM cost understanding | PERFORMANCE_AND_COST | measured | Partial | Embed RSS/512m bench recorded; LLM cost TBD |
| SUB-1 | GitHub repo with history | git | `5c4d02c` on origin/main | Partial | History started; more phase commits needed |
| SUB-2 | Live demo link | README | `phase1_deploy.txt` | Done-verified | https://ai-investigation-engine-scyz.onrender.com |
| SUB-3 | README | README.md | review | Not started | — |
| SUB-4 | Evaluation report | EVALUATION_REPORT | evidence | Not started | — |
| SUB-5 | AI usage report | AI_USAGE_REPORT | owner fill-in | Not started | — |
| INT-1 | Interview/docs/exercises | guides + drills | TBD | Not started | — |
