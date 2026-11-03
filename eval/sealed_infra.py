"""Sealed-evaluation infrastructure: bookkeeping, fingerprints, budgets.

Does not score sealed gold answers. Pure helpers used by ``run_sealed_final``.
Frozen candidate knobs are constants here for drift checks — keep in sync with
``docs/evidence/final_candidate_freeze.md`` (SOFT / 0.65 / hybrid_rrf /
verify_final_v1 / bridge=1).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from app.llm.prompts.reader import READER_SYSTEM

ROOT = Path(__file__).resolve().parents[1]

# Frozen candidate — do not change without a new freeze document.
PROMPT_ID = "reader_v2_phase_c"
VERIFY_ID = "verify_final_v1"
RETRIEVAL_MODE = "hybrid_rrf"
TOP_K = 10
COVERAGE = 0.65
POLICY = "soft"
BRIDGE_ROUNDS = 1
CANDIDATE_CONFIG_ID = "sealed_candidate_soft"
LEGACY_CONFIG_ID = "sealed_legacy"

SlotStatus = Literal["pending", "completed", "failed"]


class SealedDriftError(RuntimeError):
    """Checkpoint resume rejected due to config/model drift."""


class SealedBudgetExhausted(RuntimeError):
    """Daily request/token budget reached; pause for another calendar day."""


@dataclass
class FrozenCandidateSpec:
    prompt_id: str = PROMPT_ID
    verify_id: str = VERIFY_ID
    retrieval_mode: str = RETRIEVAL_MODE
    top_k: int = TOP_K
    coverage_threshold: float = COVERAGE
    multi_hop_policy: str = POLICY
    bridge_rounds: int = BRIDGE_ROUNDS
    experimental_passage_reader: bool = True


FROZEN_CANDIDATE = FrozenCandidateSpec()


def prompt_sha256() -> str:
    return hashlib.sha256(READER_SYSTEM.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def config_fingerprint(
    *,
    config_id: str,
    model_id: str,
    corpus: dict[str, Any],
    git_commit: str | None,
    candidate: FrozenCandidateSpec | None = None,
) -> str:
    """Stable hash of settings that must not drift across resume."""
    spec = candidate or FROZEN_CANDIDATE
    payload = {
        "config_id": config_id,
        "model_id": model_id,
        "git_commit": git_commit or "",
        "prompt_id": spec.prompt_id,
        "prompt_sha256": prompt_sha256(),
        "verify_id": spec.verify_id,
        "retrieval_mode": spec.retrieval_mode,
        "top_k": spec.top_k,
        "coverage_threshold": spec.coverage_threshold,
        "multi_hop_policy": spec.multi_hop_policy,
        "bridge_rounds": spec.bridge_rounds,
        "experimental_passage_reader": (
            spec.experimental_passage_reader
            if config_id == CANDIDATE_CONFIG_ID
            else False
        ),
        "corpus_active_documents": corpus.get("active_documents"),
        "corpus_chunk_rows": corpus.get("chunk_rows"),
        "index_fingerprint": corpus.get("index_fingerprint"),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_validity_key(
    *,
    config_id: str,
    question_id: str,
    model_id: str,
    config_fp: str,
    passage_fingerprint: str,
    prompt_sha: str,
    verify_id: str,
) -> str:
    blob = "|".join(
        [
            config_id,
            question_id,
            model_id,
            config_fp,
            passage_fingerprint,
            prompt_sha,
            verify_id,
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def passage_fingerprint_from_texts(parts: list[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


@dataclass
class QuestionSlot:
    question_id: str
    status: SlotStatus = "pending"
    error: str | None = None
    result: dict[str, Any] | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuestionSlot:
        return cls(
            question_id=str(data["question_id"]),
            status=str(data.get("status") or "pending"),  # type: ignore[arg-type]
            error=data.get("error"),
            result=data.get("result"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class DailyBudget:
    """Calendar-day ceilings; not a provider probe."""

    max_requests: int
    max_tokens: int
    day: str = field(default_factory=lambda: date.today().isoformat())
    requests_used: int = 0
    tokens_used: int = 0

    def remaining_requests(self) -> int:
        return max(0, self.max_requests - self.requests_used)

    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.tokens_used)

    def can_afford(self, *, requests: int = 1, tokens: int = 0) -> bool:
        if self.day != date.today().isoformat():
            return True  # caller should reset
        return (
            self.requests_used + requests <= self.max_requests
            and self.tokens_used + tokens <= self.max_tokens
        )

    def record(self, *, requests: int, tokens: int) -> None:
        today = date.today().isoformat()
        if self.day != today:
            self.day = today
            self.requests_used = 0
            self.tokens_used = 0
        self.requests_used += max(0, requests)
        self.tokens_used += max(0, tokens)

    def ensure_day(self) -> None:
        today = date.today().isoformat()
        if self.day != today:
            self.day = today
            self.requests_used = 0
            self.tokens_used = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DailyBudget:
        return cls(
            max_requests=int(data["max_requests"]),
            max_tokens=int(data["max_tokens"]),
            day=str(data.get("day") or date.today().isoformat()),
            requests_used=int(data.get("requests_used") or 0),
            tokens_used=int(data.get("tokens_used") or 0),
        )


def init_slots(question_ids: list[str]) -> dict[str, QuestionSlot]:
    return {qid: QuestionSlot(question_id=qid) for qid in question_ids}


def slot_counts(slots: dict[str, QuestionSlot]) -> dict[str, int]:
    counts = {"pending": 0, "completed": 0, "failed": 0, "expected": len(slots)}
    for slot in slots.values():
        counts[slot.status] = counts.get(slot.status, 0) + 1
    return counts


def mark_completed(
    slots: dict[str, QuestionSlot], question_id: str, result: dict[str, Any]
) -> None:
    slots[question_id] = QuestionSlot(
        question_id=question_id,
        status="completed",
        result=result,
        updated_at=datetime.now(UTC).isoformat(),
    )


def mark_failed(
    slots: dict[str, QuestionSlot], question_id: str, error: str
) -> None:
    slots[question_id] = QuestionSlot(
        question_id=question_id,
        status="failed",
        error=error[:500],
        updated_at=datetime.now(UTC).isoformat(),
    )


def is_config_complete(slots: dict[str, QuestionSlot]) -> bool:
    """True only when every expected ID is completed or failed (none pending)."""
    if not slots:
        return False
    return all(s.status != "pending" for s in slots.values())


def has_valid_comparison_results(
    slots: dict[str, QuestionSlot], *, min_completed: int = 1
) -> bool:
    completed = sum(1 for s in slots.values() if s.status == "completed")
    return completed >= min_completed and is_config_complete(slots)


def sealed_run_complete(
    configs: dict[str, dict[str, QuestionSlot]],
    *,
    required_config_ids: list[str],
) -> bool:
    for cid in required_config_ids:
        slots = configs.get(cid)
        if slots is None or not has_valid_comparison_results(slots):
            return False
    return True


def aggregate_slots(slots: dict[str, QuestionSlot]) -> dict[str, Any]:
    """Denominators always include expected/pending; never drop IDs."""
    counts = slot_counts(slots)
    completed_rows = [
        s.result for s in slots.values() if s.status == "completed" and s.result
    ]
    failed_rows = [
        {"question_id": s.question_id, "error": s.error}
        for s in slots.values()
        if s.status == "failed"
    ]
    pending_ids = [s.question_id for s in slots.values() if s.status == "pending"]
    n_expected = counts["expected"]
    n_completed = counts["completed"]
    n_failed = counts["failed"]
    n_pending = counts["pending"]
    n_terminal = n_completed + n_failed
    return {
        "n_expected": n_expected,
        "n_completed": n_completed,
        "n_failed": n_failed,
        "n_pending": n_pending,
        "n_terminal": n_terminal,
        "n_attempted": n_terminal,  # executed attempts
        "n_scored": n_completed,
        "completion_rate": (n_terminal / n_expected) if n_expected else 0.0,
        "config_complete": is_config_complete(slots),
        "pending_question_ids": pending_ids,
        "failed_question_ids": [r["question_id"] for r in failed_rows],
        "n_completed_results": len(completed_rows),
    }


@dataclass
class ConfigCheckpoint:
    run_id: str
    config_id: str
    config_fingerprint: str
    model_id: str
    prompt_id: str
    prompt_sha256: str
    verify_id: str
    retrieval_mode: str
    coverage_threshold: float
    multi_hop_policy: str
    bridge_rounds: int
    experimental_passage_reader: bool
    sealed_sha256: str
    freeze_sha256: str
    corpus: dict[str, Any]
    git_commit: str | None
    question_ids: list[str]
    slots: dict[str, QuestionSlot]
    budget: DailyBudget
    consecutive_provider_failures: int = 0
    paused: bool = False
    pause_reason: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_id": self.config_id,
            "config_fingerprint": self.config_fingerprint,
            "model_id": self.model_id,
            "prompt_id": self.prompt_id,
            "prompt_sha256": self.prompt_sha256,
            "verify_id": self.verify_id,
            "retrieval_mode": self.retrieval_mode,
            "coverage_threshold": self.coverage_threshold,
            "multi_hop_policy": self.multi_hop_policy,
            "bridge_rounds": self.bridge_rounds,
            "experimental_passage_reader": self.experimental_passage_reader,
            "sealed_sha256": self.sealed_sha256,
            "freeze_sha256": self.freeze_sha256,
            "corpus": self.corpus,
            "git_commit": self.git_commit,
            "question_ids": list(self.question_ids),
            "slots": {k: v.to_dict() for k, v in self.slots.items()},
            "budget": self.budget.to_dict(),
            "consecutive_provider_failures": self.consecutive_provider_failures,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "slot_counts": slot_counts(self.slots),
            "config_complete": is_config_complete(self.slots),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigCheckpoint:
        slots_raw = data.get("slots") or {}
        slots = {
            str(k): QuestionSlot.from_dict(v) if isinstance(v, dict) else v
            for k, v in slots_raw.items()
        }
        # Re-hydrate any missing expected IDs as pending (never drop).
        for qid in data.get("question_ids") or []:
            if qid not in slots:
                slots[str(qid)] = QuestionSlot(question_id=str(qid))
        return cls(
            run_id=str(data["run_id"]),
            config_id=str(data["config_id"]),
            config_fingerprint=str(data["config_fingerprint"]),
            model_id=str(data.get("model_id") or ""),
            prompt_id=str(data.get("prompt_id") or PROMPT_ID),
            prompt_sha256=str(data.get("prompt_sha256") or ""),
            verify_id=str(data.get("verify_id") or VERIFY_ID),
            retrieval_mode=str(data.get("retrieval_mode") or RETRIEVAL_MODE),
            coverage_threshold=float(data.get("coverage_threshold") or COVERAGE),
            multi_hop_policy=str(data.get("multi_hop_policy") or POLICY),
            bridge_rounds=int(data.get("bridge_rounds") or BRIDGE_ROUNDS),
            experimental_passage_reader=bool(
                data.get("experimental_passage_reader")
            ),
            sealed_sha256=str(data.get("sealed_sha256") or ""),
            freeze_sha256=str(data.get("freeze_sha256") or ""),
            corpus=dict(data.get("corpus") or {}),
            git_commit=data.get("git_commit"),
            question_ids=[str(x) for x in (data.get("question_ids") or [])],
            slots=slots,
            budget=DailyBudget.from_dict(data["budget"])
            if data.get("budget")
            else DailyBudget(max_requests=0, max_tokens=0),
            consecutive_provider_failures=int(
                data.get("consecutive_provider_failures") or 0
            ),
            paused=bool(data.get("paused")),
            pause_reason=data.get("pause_reason"),
            created_at=str(data.get("created_at") or datetime.now(UTC).isoformat()),
            updated_at=str(data.get("updated_at") or datetime.now(UTC).isoformat()),
        )


def assert_resume_compatible(
    checkpoint: ConfigCheckpoint,
    *,
    expected_fp: str,
    expected_model_id: str,
    expected_sealed_sha: str,
    expected_prompt_sha: str,
) -> None:
    if checkpoint.config_fingerprint != expected_fp:
        raise SealedDriftError(
            f"config_fingerprint drift: checkpoint={checkpoint.config_fingerprint} "
            f"current={expected_fp}"
        )
    if checkpoint.model_id != expected_model_id:
        raise SealedDriftError(
            f"model_id drift: checkpoint={checkpoint.model_id!r} "
            f"current={expected_model_id!r}"
        )
    if checkpoint.sealed_sha256 != expected_sealed_sha:
        raise SealedDriftError("sealed file SHA-256 drift; refusing resume")
    if checkpoint.prompt_sha256 and checkpoint.prompt_sha256 != expected_prompt_sha:
        raise SealedDriftError("prompt_sha256 drift; refusing resume")


def is_provider_failure(error: str) -> bool:
    err = error.lower()
    return any(
        x in err
        for x in (
            "quota",
            "rate",
            "unavailable",
            "429",
            "403",
            "budget",
            "tpm",
            "rpm",
            "rpd",
        )
    )


def load_sealed_question_ids(manifest_path: Path, sealed_path: Path) -> list[str]:
    """Load sealed IDs from manifest when present; else IDs only from sealed file.

    Does not return gold answers.
    """
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ids = [str(x) for x in (manifest.get("test_ids") or [])]
        if ids:
            return ids
    # Fallback: IDs only (callers must not log gold fields).
    payload = json.loads(sealed_path.read_text(encoding="utf-8"))
    return [str(q["id"]) for q in (payload.get("questions") or []) if q.get("id")]


def load_sealed_questions_by_id(sealed_path: Path) -> dict[str, dict[str, Any]]:
    """Map id → question object for execution. Prefer not printing gold fields."""
    payload = json.loads(sealed_path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for q in payload.get("questions") or []:
        qid = str(q.get("id") or "")
        if qid:
            out[qid] = q
    return out
