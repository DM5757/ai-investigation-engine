# Phase 4 notes — LLM gateway + investigation engine

## Key modules

1. `app.llm.gateway.LLMGateway.chat` — Groq→Gemini provider chain, retries, budget, optional cache.
2. `app.llm.gateway.OpenAICompatibleClient` — OpenAI SDK with Groq / Gemini OpenAI base_url.
3. `app.llm.retry.with_retries` — exponential backoff + jitter; honour Retry-After on 429.
4. `app.llm.json_repair.parse_model` — JSON mode validation + one repair → `LLMOutputInvalid`.
5. `app.llm.scripted.ScriptedLLM` — deterministic `LLMClient` for unit/integration tests.
6. `app.investigation.engine.InvestigationEngine.investigate` — hand-written stages (no LangChain).
7. `app.investigation.planner.plan_question` — LLM plan or deterministic single sub-question.
8. `app.investigation.tools.ToolExecutor` — search / context / metadata / find / record_finding.
9. `app.investigation.extractor.quote_appears_in_chunk` — normalized quote verification.
10. `app.investigation.contradictions.candidate_conflicts` — polarity/numeric disagreement.
11. `app.investigation.sufficiency.assess_sufficiency` — answered|partial|conflicting|insufficient.
12. `app.investigation.synthesizer` + `verifier` — cite only verified claims; strip fabricated [Sn].
13. `app.investigation.injection.scan_injection` — wrap + heuristic down-weight / block tools.

## Design notes

- Never combine Groq tools with `response_format` json_schema in one call.
- When no API keys are configured, return degraded `llm_unavailable` with retrieved evidence rather than inventing answers.
- Quote verification normalizes whitespace/case so fabricated citations fail closed.
- Contradiction candidates require polarity/numeric disagreement, not mere paraphrase.
- Budget exhaustion raises `BudgetExceeded` and maps to explicit degraded status.
- `ScriptedLLM` proves RAG behavior without burning free-tier quota.

## Live evidence (2026-10-29)

- `make test-live` → **1 passed** (Groq `openai/gpt-oss-120b`)
- Multi-doc PaymentService question → `answered` with verified citations (`live_a`, `live_b`)
- Artifact: `docs/evidence/phase4_live_trace.json`
- Default pytest uses `-m "not live"`; use `make test-live` for LLM.

## Limits

- Dedicated live smokes for abstention / contradiction / injection are covered primarily by scripted tests; production re-validation is quota-sensitive.
- Free-tier TPM/TPD can interrupt investigation mid-run; answer eval must report skips honestly.
