"""Sealed-evaluation infrastructure: bookkeeping, drift, budgets, fidelity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.sealed_infra import (
    BRIDGE_ROUNDS,
    CANDIDATE_CONFIG_ID,
    COVERAGE,
    FROZEN_CANDIDATE,
    LEGACY_CONFIG_ID,
    POLICY,
    PROMPT_ID,
    RETRIEVAL_MODE,
    VERIFY_ID,
    ConfigCheckpoint,
    DailyBudget,
    QuestionSlot,
    SealedDriftError,
    aggregate_slots,
    assert_resume_compatible,
    cache_validity_key,
    config_fingerprint,
    has_valid_comparison_results,
    init_slots,
    is_config_complete,
    mark_completed,
    mark_failed,
    prompt_sha256,
    sealed_run_complete,
    slot_counts,
)


def test_early_stop_preserves_pending_ids() -> None:
    ids = [f"q{i}" for i in range(5)]
    slots = init_slots(ids)
    mark_completed(slots, "q0", {"status": "answered", "answer_text": "a"})
    mark_failed(slots, "q1", "gemini:rate_limit_rpm")
    # Simulate early stop: q2..q4 remain pending
    counts = slot_counts(slots)
    assert counts["expected"] == 5
    assert counts["completed"] == 1
    assert counts["failed"] == 1
    assert counts["pending"] == 3
    summary = aggregate_slots(slots)
    assert summary["n_pending"] == 3
    assert set(summary["pending_question_ids"]) == {"q2", "q3", "q4"}
    assert not summary["config_complete"]
    assert not is_config_complete(slots)


def test_sealed_complete_requires_all_configs_terminal() -> None:
    ids = ["a", "b"]
    cand = init_slots(ids)
    leg = init_slots(ids)
    mark_completed(cand, "a", {"status": "answered"})
    mark_completed(cand, "b", {"status": "insufficient"})
    mark_completed(leg, "a", {"status": "answered"})
    # legacy still pending b
    assert not sealed_run_complete(
        {CANDIDATE_CONFIG_ID: cand, LEGACY_CONFIG_ID: leg},
        required_config_ids=[CANDIDATE_CONFIG_ID, LEGACY_CONFIG_ID],
    )
    mark_failed(leg, "b", "quota")
    assert sealed_run_complete(
        {CANDIDATE_CONFIG_ID: cand, LEGACY_CONFIG_ID: leg},
        required_config_ids=[CANDIDATE_CONFIG_ID, LEGACY_CONFIG_ID],
    )


def test_never_complete_with_zero_completed() -> None:
    slots = init_slots(["x", "y"])
    mark_failed(slots, "x", "err")
    mark_failed(slots, "y", "err")
    assert is_config_complete(slots)
    assert not has_valid_comparison_results(slots, min_completed=1)


def test_drift_rejects_resume() -> None:
    budget = DailyBudget(max_requests=10, max_tokens=1000)
    ck = ConfigCheckpoint(
        run_id="r1",
        config_id=CANDIDATE_CONFIG_ID,
        config_fingerprint="abc",
        model_id="model-a",
        prompt_id=PROMPT_ID,
        prompt_sha256=prompt_sha256(),
        verify_id=VERIFY_ID,
        retrieval_mode=RETRIEVAL_MODE,
        coverage_threshold=COVERAGE,
        multi_hop_policy=POLICY,
        bridge_rounds=BRIDGE_ROUNDS,
        experimental_passage_reader=True,
        sealed_sha256="sealed",
        freeze_sha256="freeze",
        corpus={"active_documents": 1},
        git_commit="deadbeef",
        question_ids=["q1"],
        slots=init_slots(["q1"]),
        budget=budget,
    )
    with pytest.raises(SealedDriftError, match="config_fingerprint"):
        assert_resume_compatible(
            ck,
            expected_fp="other",
            expected_model_id="model-a",
            expected_sealed_sha="sealed",
            expected_prompt_sha=prompt_sha256(),
        )
    with pytest.raises(SealedDriftError, match="model_id"):
        assert_resume_compatible(
            ck,
            expected_fp="abc",
            expected_model_id="model-b",
            expected_sealed_sha="sealed",
            expected_prompt_sha=prompt_sha256(),
        )


def test_checkpoint_rehydrates_missing_slot_ids() -> None:
    budget = DailyBudget(max_requests=5, max_tokens=100)
    data = {
        "run_id": "r",
        "config_id": LEGACY_CONFIG_ID,
        "config_fingerprint": "fp",
        "model_id": "m",
        "prompt_id": PROMPT_ID,
        "prompt_sha256": prompt_sha256(),
        "verify_id": VERIFY_ID,
        "retrieval_mode": RETRIEVAL_MODE,
        "coverage_threshold": COVERAGE,
        "multi_hop_policy": POLICY,
        "bridge_rounds": 0,
        "experimental_passage_reader": False,
        "sealed_sha256": "s",
        "freeze_sha256": "f",
        "corpus": {},
        "git_commit": None,
        "question_ids": ["q1", "q2", "q3"],
        "slots": {
            "q1": QuestionSlot(question_id="q1", status="completed", result={"x": 1}).to_dict()
        },
        "budget": budget.to_dict(),
    }
    ck = ConfigCheckpoint.from_dict(data)
    assert set(ck.slots) == {"q1", "q2", "q3"}
    assert ck.slots["q2"].status == "pending"
    assert ck.slots["q3"].status == "pending"


def test_cache_key_changes_with_prompt_or_passage() -> None:
    base = dict(
        config_id=CANDIDATE_CONFIG_ID,
        question_id="q1",
        model_id="m",
        config_fp="fp",
        passage_fingerprint="p1",
        prompt_sha="sha1",
        verify_id=VERIFY_ID,
    )
    k1 = cache_validity_key(**base)
    k2 = cache_validity_key(**{**base, "passage_fingerprint": "p2"})
    k3 = cache_validity_key(**{**base, "prompt_sha": "sha2"})
    assert k1 != k2
    assert k1 != k3


def test_daily_budget_rolls_calendar_day(monkeypatch: pytest.MonkeyPatch) -> None:
    b = DailyBudget(max_requests=2, max_tokens=100, day="2000-01-01", requests_used=2)
    b.ensure_day()
    assert b.requests_used == 0
    assert b.can_afford(requests=1)


def test_frozen_candidate_spec_matches_freeze_knobs() -> None:
    assert FROZEN_CANDIDATE.multi_hop_policy == "soft"
    assert FROZEN_CANDIDATE.coverage_threshold == 0.65
    assert FROZEN_CANDIDATE.retrieval_mode == "hybrid_rrf"
    assert FROZEN_CANDIDATE.verify_id == "verify_final_v1"
    assert FROZEN_CANDIDATE.bridge_rounds == 1
    assert FROZEN_CANDIDATE.experimental_passage_reader is True


def test_candidate_fingerprint_includes_bridge_and_experimental() -> None:
    fp_a = config_fingerprint(
        config_id=CANDIDATE_CONFIG_ID,
        model_id="m",
        corpus={"active_documents": 55081, "chunk_rows": 1},
        git_commit="abc",
    )
    fp_b = config_fingerprint(
        config_id=LEGACY_CONFIG_ID,
        model_id="m",
        corpus={"active_documents": 55081, "chunk_rows": 1},
        git_commit="abc",
    )
    assert fp_a != fp_b


def test_apply_frozen_settings_candidate_fidelity() -> None:
    from app.config import Settings
    from eval.run_sealed_final import _apply_frozen_settings

    s = Settings(DATABASE_URL="sqlite+pysqlite:///:memory:")
    _apply_frozen_settings(s, experimental=True)
    assert s.experimental_passage_reader is True
    assert s.reader_multi_hop_policy == "soft"
    assert abs(s.reader_coverage_threshold - 0.65) < 1e-9
    assert s.reader_max_bridge_rounds == 1
    assert s.reader_preferred_mode == "hybrid_rrf"
    _apply_frozen_settings(s, experimental=False)
    assert s.experimental_passage_reader is False


def test_manifest_ids_without_opening_gold_fields() -> None:
    """Use phase_b manifest test_ids only (no sealed gold inspection)."""
    manifest = Path("eval/questions/phase_b_bench_v1_manifest.json")
    if not manifest.is_file():
        pytest.skip("manifest missing")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    ids = data.get("test_ids") or []
    assert len(ids) == 300
    # Ensure sealed file hash still matches without reading question bodies here.
    from eval.sealed_infra import sha256_file

    sealed = Path("eval/questions/phase_b_bench_v1_test_sealed.json")
    live = sha256_file(sealed)
    assert data["file_sha256"]["phase_b_bench_v1_test_sealed.json"] == live
