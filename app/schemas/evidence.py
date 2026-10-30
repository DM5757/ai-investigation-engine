"""Evidence and investigation response schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AnswerStatus = Literal[
    "answered",
    "partial",
    "conflicting",
    "insufficient",
    "llm_unavailable",
]


class SubQuestion(BaseModel):
    """One decomposable unit of an investigation plan."""

    id: str
    text: str
    depends_on: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """Structured investigation plan produced by the planner."""

    question_type: str = "factual"
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    expected_answer_shape: str = "short_paragraph"


class Claim(BaseModel):
    """A single evidence-backed assertion extracted from a chunk."""

    claim_id: str
    subject: str
    attribute: str
    value: str
    quote: str
    chunk_id: str
    doc_id: str
    verified: bool = False
    source_label: str | None = None
    source_title: str | None = None
    confidence: float = 1.0


class Conflict(BaseModel):
    """Two or more claims that disagree on the same subject/attribute."""

    subject: str
    attribute: str
    sides: list[Claim] = Field(default_factory=list)
    adjudication: str | None = None


class Finding(BaseModel):
    """Intermediate note recorded by the tool loop."""

    finding_id: str
    text: str
    related_chunk_ids: list[str] = Field(default_factory=list)
    related_doc_ids: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    """Source pointer used in the synthesized answer."""

    label: str
    chunk_id: str
    doc_id: str
    quote: str


class UsageStats(BaseModel):
    """Token / call accounting for one stage or whole run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0

    def add(self, other: UsageStats) -> UsageStats:
        return UsageStats(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            calls=self.calls + other.calls,
        )


class TraceEvent(BaseModel):
    """One stage of the investigation state machine."""

    stage: str
    inputs_summary: str = ""
    outputs_summary: str = ""
    latency_ms: float = 0.0
    tokens: UsageStats = Field(default_factory=UsageStats)
    extra: dict[str, Any] = Field(default_factory=dict)


class AnswerResponse(BaseModel):
    """Final investigation result returned to callers."""

    status: AnswerStatus
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    plan: Plan | None = None
    abstention_reason: str | None = None
    evidence_preview: list[dict[str, Any]] = Field(default_factory=list)
    usage: UsageStats = Field(default_factory=UsageStats)
    degraded: bool = False
    trace: list[TraceEvent] = Field(default_factory=list)
