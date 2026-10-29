# Phase 4 notes — LLM gateway + investigation engine

## Key functions (interview map)

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

## Interview questions

1. Why never combine Groq tools with `response_format` json_schema in one call?
2. How does degraded mode behave when no API keys are configured?
3. Walk quote verification: what normalization prevents fabricated citations?
4. How do contradiction candidates avoid flagging mere paraphrases as conflicts?
5. Where does the budget raise `BudgetExceeded`, and what status does the engine return?
6. How does the injection scanner interact with `read_chunk_context`?
7. Why is `ScriptedLLM` sufficient to prove RAG-2..RAG-8 without burning free-tier quota?

## Limits

- Live LLM smoke **not** completed this session (keys absent).
- Qdrant Cloud remote unverified; bm25_avgdl default; CRC32 collisions pending; retrieval eval pending.
- Phase 5 (API/UI) not started.
