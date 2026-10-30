"""Question planning with LLM JSON mode and deterministic fallback."""

from __future__ import annotations

from app.errors import BudgetExceeded, LLMOutputInvalid, LLMUnavailable
from app.llm.json_repair import parse_model
from app.llm.prompts.planner import PLANNER_SYSTEM
from app.llm.types import ChatMessage, LLMClient
from app.schemas.evidence import Plan, SubQuestion, UsageStats


def deterministic_plan(question: str) -> Plan:
    """Single sub-question plan used when LLM is unavailable or fails."""
    return Plan(
        question_type="factual",
        sub_questions=[SubQuestion(id="q1", text=question.strip(), depends_on=[])],
        expected_answer_shape="short_paragraph",
    )


def _clamp_plan(plan: Plan, max_sub_questions: int) -> Plan:
    subs = plan.sub_questions[: max(1, max_sub_questions)]
    if not subs:
        return deterministic_plan("(empty)")
    return plan.model_copy(update={"sub_questions": subs})


def plan_question(
    question: str,
    llm: LLMClient | None,
    *,
    max_sub_questions: int = 4,
) -> tuple[Plan, UsageStats, bool]:
    """Return (plan, usage, used_llm)."""
    if llm is None:
        return deterministic_plan(question), UsageStats(), False
    messages = [
        ChatMessage(role="system", content=PLANNER_SYSTEM),
        ChatMessage(role="user", content=question),
    ]
    try:
        result = llm.chat(
            messages,
            response_format={"type": "json_object"},
            stage="plan",
        )
    except BudgetExceeded:
        raise
    except (LLMUnavailable, LLMOutputInvalid, Exception):
        return deterministic_plan(question), UsageStats(), False
    raw = result.content or ""
    try:
        plan = parse_model(raw, Plan)
    except LLMOutputInvalid:
        return deterministic_plan(question), result.usage, False
    return _clamp_plan(plan, max_sub_questions), result.usage, True
