"""One-shot sealed evaluation harness (infrastructure-hardened).

Requires ``--confirm-sealed-unlock YES``. Does not tune on sealed answers.

Candidate path = frozen production-equivalent experimental reader pipeline:
  EXPERIMENTAL_PASSAGE_READER=true, SOFT, coverage 0.65, bridge rounds 1,
  retrieval hybrid_rrf (InvestigationEngine._finalize_with_reader).

Legacy path = same retrieval mode with experimental flag false.

Bookkeeping: every expected question ID stays pending|completed|failed.
``sealed_complete`` is true only when both configs have zero pending IDs and
at least one completed result each.

Daily budgets / pause: stop the session without dropping pending IDs; resume
with the same ``--run-id`` after verifying config fingerprints.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_e0_reader import _resolve_gold_doc_ids  # noqa: E402
from eval.run_eval import _build_doc_maps, _build_stack, _run_investigation  # noqa: E402
from eval.run_final_push import _aggregate, _score  # noqa: E402
from eval.sealed_infra import (  # noqa: E402
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
    SealedBudgetExhausted,
    SealedDriftError,
    aggregate_slots,
    assert_resume_compatible,
    cache_validity_key,
    config_fingerprint,
    has_valid_comparison_results,
    is_infra_failure_result,
    is_provider_failure,
    load_sealed_question_ids,
    load_sealed_questions_by_id,
    mark_completed,
    mark_failed,
    prompt_sha256,
    sealed_run_complete,
    sha256_file,
    slot_counts,
)
from scripts._phase6_common import (  # noqa: E402
    ensure_dirs,
    neon_doc_counts,
    write_json,
)

SEALED_PATH = ROOT / "eval" / "questions" / "phase_b_bench_v1_test_sealed.json"
MANIFEST_PATH = ROOT / "eval" / "questions" / "phase_b_bench_v1_manifest.json"
RESULTS_DIR = ROOT / "eval" / "results"
CACHE_DIR = ROOT / "data" / "cache" / "sealed_final"
CHECKPOINT_DIR = ROOT / "data" / "checkpoints" / "sealed_final"
DEFAULT_FREEZE = ROOT / "docs" / "evidence" / "final_candidate_freeze.md"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_checkpoint(path: Path, ck: ConfigCheckpoint) -> None:
    ck.updated_at = datetime.now(UTC).isoformat()
    write_json(path, ck.to_dict())


def _read_result_cache(key: str) -> dict[str, Any] | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.is_file():
        return None
    data = _load(path)
    # Validity envelope
    if data.get("prompt_sha256") != prompt_sha256():
        return None
    if data.get("verify_id") != VERIFY_ID:
        return None
    return data


def _write_result_cache(key: str, payload: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _apply_frozen_settings(settings: Any, *, experimental: bool) -> None:
    object.__setattr__(settings, "experimental_passage_reader", experimental)
    object.__setattr__(settings, "reader_multi_hop_policy", POLICY)
    object.__setattr__(settings, "reader_coverage_threshold", COVERAGE)
    object.__setattr__(settings, "reader_max_bridge_rounds", BRIDGE_ROUNDS)
    object.__setattr__(settings, "reader_preferred_mode", RETRIEVAL_MODE)
    object.__setattr__(settings, "eval_record_retention", True)


def _engine_for_config(
    *,
    config_id: str,
    settings: Any,
    retriever: Any,
    store: Any,
    llm: Any,
) -> Any:
    from app.investigation.engine import InvestigationEngine

    experimental = config_id == CANDIDATE_CONFIG_ID
    # Clone-like: mutate settings object for this engine only.
    _apply_frozen_settings(settings, experimental=experimental)
    engine = InvestigationEngine(
        retriever=retriever, store=store, llm=llm, settings=settings
    )
    engine.retriever.default_mode = RETRIEVAL_MODE  # type: ignore[assignment]
    return engine


def _result_from_investigation(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "")
    return {
        "status": status,
        "answer_text": raw.get("answer_text") or "",
        "citations": raw.get("citations") or [],
        "latency_s": raw.get("latency_s"),
        "llm_calls": raw.get("llm_calls") or 0,
        "tokens": raw.get("tokens") or 0,
        "answer_supported": status in ("answered", "partial"),
        "evidence_chain_ok": status == "answered",
        "abstention_reason": raw.get("abstention_reason"),
        "trace_stages": raw.get("trace_stages") or [],
        "retrieved_doc_ids": raw.get("retrieved_doc_ids") or [],
        "retention": raw.get("retention"),
        "reader_path": "experimental_passage_reader"
        if "passage_reader" in (raw.get("trace_stages") or [])
        or "reader_bridge_search" in (raw.get("trace_stages") or [])
        else "legacy",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sealed evaluation (hardened)")
    parser.add_argument("--confirm-sealed-unlock", type=str, default="")
    parser.add_argument("--freeze-manifest", type=str, default=str(DEFAULT_FREEZE))
    parser.add_argument("--run-id", type=str, required=True)
    parser.add_argument(
        "--configs",
        default=f"{CANDIDATE_CONFIG_ID},{LEGACY_CONFIG_ID}",
    )
    parser.add_argument("--pause-s", type=float, default=1.5)
    parser.add_argument(
        "--provider-backoff-s",
        type=float,
        default=15.0,
        help="Sleep after a provider failure before the next attempt.",
    )
    parser.add_argument("--stop-after-llm-unavailable", type=int, default=5)
    parser.add_argument(
        "--max-requests-today",
        type=int,
        default=200,
        help="Soft daily request ceiling for this run (free-tier safe default).",
    )
    parser.add_argument(
        "--max-tokens-today",
        type=int,
        default=180_000,
        help="Soft daily token ceiling (below typical Groq 200K TPD).",
    )
    parser.add_argument(
        "--max-questions-this-session",
        type=int,
        default=0,
        help="Optional per-session cap; 0 = unlimited within daily budget.",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="Mark run paused and exit without evaluating further questions.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing run-id (required when checkpoint exists).",
    )
    args = parser.parse_args()

    if args.confirm_sealed_unlock != "YES":
        print(
            "ERROR: refuse sealed run without --confirm-sealed-unlock YES",
            file=sys.stderr,
        )
        sys.exit(2)

    freeze_path = Path(args.freeze_manifest)
    if not freeze_path.is_file():
        print(f"ERROR: missing freeze manifest {freeze_path}", file=sys.stderr)
        sys.exit(2)
    if not SEALED_PATH.is_file():
        print(f"ERROR: missing sealed file {SEALED_PATH}", file=sys.stderr)
        sys.exit(1)

    ensure_dirs()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    sealed_sha = sha256_file(SEALED_PATH)
    freeze_sha = sha256_file(freeze_path)
    question_ids = load_sealed_question_ids(MANIFEST_PATH, SEALED_PATH)
    if len(question_ids) != 300:
        print(
            f"WARNING: expected 300 sealed IDs, found {len(question_ids)}",
            file=sys.stderr,
        )

    from app.build_info import resolve_git_commit
    from app.config import get_settings
    from app.deps import get_or_create_llm, reset_process_singletons
    from scripts._phase6_common import open_session

    settings = get_settings()
    reset_process_singletons()
    session = open_session(settings)
    title_to, path_to, ext_to = _build_doc_maps(session)
    corpus = dict(neon_doc_counts(settings) or {})
    corpus["index_fingerprint"] = (
        f"strategy={getattr(settings, 'chunk_strategy', '')}|"
        f"embed={getattr(settings, 'embedding_model_short', '')}|"
        f"active={corpus.get('active_documents')}"
    )
    store, retriever, _ = _build_stack(settings, RETRIEVAL_MODE)
    llm = get_or_create_llm(settings)
    if llm is None:
        print("ERROR: no LLM configured", file=sys.stderr)
        sys.exit(1)

    model_id = str(
        getattr(settings, "groq_model", "") or getattr(settings, "gemini_model", "") or ""
    )
    git_commit = resolve_git_commit(configured=settings.git_commit)
    p_sha = prompt_sha256()
    config_ids = [c.strip() for c in args.configs.split(",") if c.strip()]
    questions_by_id: dict[str, dict[str, Any]] | None = None

    if args.pause:
        for cfg_id in config_ids:
            ck_path = CHECKPOINT_DIR / f"{args.run_id}__{cfg_id}.json"
            if not ck_path.is_file():
                print(f"ERROR: cannot --pause; missing {ck_path}", file=sys.stderr)
                sys.exit(2)
            ck = ConfigCheckpoint.from_dict(_load(ck_path))
            ck.paused = True
            ck.pause_reason = "operator_pause"
            _write_checkpoint(ck_path, ck)
            print(f"paused {cfg_id}: {slot_counts(ck.slots)}", flush=True)
        sys.exit(0)

    summaries: list[dict[str, Any]] = []
    config_slots: dict[str, dict[str, Any]] = {}

    for cfg_id in config_ids:
        experimental = cfg_id == CANDIDATE_CONFIG_ID
        _apply_frozen_settings(settings, experimental=experimental)

        expected_fp = config_fingerprint(
            config_id=cfg_id,
            model_id=model_id,
            corpus=corpus,
            git_commit=git_commit,
            candidate=FROZEN_CANDIDATE,
        )
        ck_path = CHECKPOINT_DIR / f"{args.run_id}__{cfg_id}.json"

        if ck_path.exists():
            if not args.resume:
                print(
                    f"ERROR: checkpoint exists for {args.run_id}/{cfg_id}; "
                    "pass --resume to continue",
                    file=sys.stderr,
                )
                sys.exit(2)
            ck = ConfigCheckpoint.from_dict(_load(ck_path))
            try:
                assert_resume_compatible(
                    ck,
                    expected_fp=expected_fp,
                    expected_model_id=model_id,
                    expected_sealed_sha=sealed_sha,
                    expected_prompt_sha=p_sha,
                )
            except SealedDriftError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                sys.exit(3)
            ck.paused = False
            ck.pause_reason = None
            # Ensure all expected IDs present.
            for qid in question_ids:
                if qid not in ck.slots:
                    from eval.sealed_infra import QuestionSlot

                    ck.slots[qid] = QuestionSlot(question_id=qid)
            ck.question_ids = list(question_ids)
        else:
            if args.resume:
                print(
                    f"ERROR: --resume set but no checkpoint at {ck_path}",
                    file=sys.stderr,
                )
                sys.exit(2)
            from eval.sealed_infra import init_slots

            ck = ConfigCheckpoint(
                run_id=args.run_id,
                config_id=cfg_id,
                config_fingerprint=expected_fp,
                model_id=model_id,
                prompt_id=PROMPT_ID,
                prompt_sha256=p_sha,
                verify_id=VERIFY_ID,
                retrieval_mode=RETRIEVAL_MODE,
                coverage_threshold=COVERAGE,
                multi_hop_policy=POLICY,
                bridge_rounds=BRIDGE_ROUNDS if experimental else 0,
                experimental_passage_reader=experimental,
                sealed_sha256=sealed_sha,
                freeze_sha256=freeze_sha,
                corpus=corpus,
                git_commit=git_commit,
                question_ids=list(question_ids),
                slots=init_slots(question_ids),
                budget=DailyBudget(
                    max_requests=args.max_requests_today,
                    max_tokens=args.max_tokens_today,
                ),
            )

        ck.budget.max_requests = args.max_requests_today
        ck.budget.max_tokens = args.max_tokens_today
        ck.budget.ensure_day()
        _write_checkpoint(ck_path, ck)

        engine = _engine_for_config(
            config_id=cfg_id,
            settings=settings,
            retriever=retriever,
            store=store,
            llm=llm,
        )
        # Fidelity check: candidate must have experimental reader + bridge=1.
        if cfg_id == CANDIDATE_CONFIG_ID:
            if not settings.experimental_passage_reader:
                print(
                    "ERROR: candidate fidelity failure — experimental flag off",
                    file=sys.stderr,
                )
                sys.exit(4)
            if int(settings.reader_max_bridge_rounds) != BRIDGE_ROUNDS:
                print(
                    "ERROR: candidate fidelity failure — bridge rounds mismatch",
                    file=sys.stderr,
                )
                sys.exit(4)

        print(
            f"SEALED config={cfg_id} expected={len(question_ids)} "
            f"slots={slot_counts(ck.slots)} experimental={experimental}",
            flush=True,
        )

        session_done = 0
        for qid in question_ids:
            slot = ck.slots[qid]
            if slot.status in ("completed", "failed"):
                continue

            ck.budget.ensure_day()
            if not ck.budget.can_afford(requests=1, tokens=0):
                ck.paused = True
                ck.pause_reason = "daily_budget"
                _write_checkpoint(ck_path, ck)
                print(
                    f"BUDGET pause {cfg_id}: {ck.budget.to_dict()}",
                    flush=True,
                )
                break
            if (
                args.max_questions_this_session > 0
                and session_done >= args.max_questions_this_session
            ):
                ck.paused = True
                ck.pause_reason = "session_cap"
                _write_checkpoint(ck_path, ck)
                print(f"SESSION pause {cfg_id} after {session_done}", flush=True)
                break

            if questions_by_id is None:
                questions_by_id = load_sealed_questions_by_id(SEALED_PATH)
            q = questions_by_id.get(qid)
            if q is None:
                mark_failed(ck.slots, qid, "missing_question_payload")
                _write_checkpoint(ck_path, ck)
                continue

            gold_docs = _resolve_gold_doc_ids(q, title_to, path_to, ext_to)
            result: dict[str, Any] = {}
            try:
                if hasattr(llm, "budget"):
                    llm.budget.reset()
                # Cache key uses question id + config fp (passage set is engine-internal;
                # fingerprint the question text as input identity).
                q_fp = cache_validity_key(
                    config_id=cfg_id,
                    question_id=qid,
                    model_id=model_id,
                    config_fp=expected_fp,
                    passage_fingerprint=f"q:{qid}:{str(q.get('question') or '')[:200]}",
                    prompt_sha=p_sha,
                    verify_id=VERIFY_ID,
                )
                cached = _read_result_cache(q_fp)
                if cached and cached.get("result"):
                    # Never treat infra-failure cache as a successful completion.
                    if is_infra_failure_result(cached.get("result")):
                        cached = None
                    else:
                        result = dict(cached["result"])
                        result["cache_hit"] = True
                if cached is None or not cached.get("result"):
                    raw = _run_investigation(
                        engine, str(q["question"]), gold_doc_ids=gold_docs
                    )
                    result = _result_from_investigation(raw)
                    result["cache_hit"] = False
                    if not is_infra_failure_result(result):
                        _write_result_cache(
                            q_fp,
                            {
                                "question_id": qid,
                                "config_id": cfg_id,
                                "model_id": model_id,
                                "config_fingerprint": expected_fp,
                                "prompt_sha256": p_sha,
                                "verify_id": VERIFY_ID,
                                "result": result,
                            },
                        )

                if is_infra_failure_result(result):
                    err = str(
                        result.get("abstention_reason")
                        or result.get("status")
                        or "llm_unavailable"
                    )
                    mark_failed(ck.slots, qid, err)
                    print(f"  INFRA_FAIL {qid}: {err[:160]}", flush=True)
                    if is_provider_failure(err):
                        ck.consecutive_provider_failures += 1
                        time.sleep(max(0.0, args.provider_backoff_s))
                        if (
                            ck.consecutive_provider_failures
                            >= args.stop_after_llm_unavailable
                        ):
                            ck.paused = True
                            ck.pause_reason = "provider_failures"
                            _write_checkpoint(ck_path, ck)
                            print(
                                f"PROVIDER pause {cfg_id} after "
                                f"{ck.consecutive_provider_failures} failures",
                                flush=True,
                            )
                            break
                    else:
                        ck.consecutive_provider_failures = 0
                else:
                    result["answer"] = _score(q, result)
                    calls = int(result.get("llm_calls") or 0)
                    tokens = int(result.get("tokens") or 0)
                    ck.budget.record(requests=max(1, calls), tokens=tokens)
                    mark_completed(ck.slots, qid, result)
                    ck.consecutive_provider_failures = 0
                    session_done += 1
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                mark_failed(ck.slots, qid, err)
                print(f"  FAIL {qid}: {err[:160]}", flush=True)
                if is_provider_failure(err):
                    ck.consecutive_provider_failures += 1
                    time.sleep(max(0.0, args.provider_backoff_s))
                    if (
                        ck.consecutive_provider_failures
                        >= args.stop_after_llm_unavailable
                    ):
                        ck.paused = True
                        ck.pause_reason = "provider_failures"
                        _write_checkpoint(ck_path, ck)
                        print(
                            f"PROVIDER pause {cfg_id} after "
                            f"{ck.consecutive_provider_failures} failures",
                            flush=True,
                        )
                        break
                else:
                    ck.consecutive_provider_failures = 0

            _write_checkpoint(ck_path, ck)
            if not (ck.slots[qid].result or {}).get("cache_hit"):
                time.sleep(max(0.0, args.pause_s))

        # Build scored rows for metrics ONLY from completed slots; keep denominators.
        per_q: list[dict[str, Any]] = []
        for qid in question_ids:
            slot = ck.slots[qid]
            row: dict[str, Any] = {
                "question_id": qid,
                "slot_status": slot.status,
            }
            if slot.status == "completed" and slot.result:
                row.update(slot.result)
            elif slot.status == "failed":
                row["error"] = slot.error
                row["status"] = "error"
            else:
                row["status"] = "pending"
            per_q.append(row)

        slot_summary = aggregate_slots(ck.slots)
        # Answer metrics over completed only; expose pending in slot_summary.
        completed_for_metrics = [
            r for r in per_q if r.get("slot_status") == "completed" and "answer" in r
        ]
        metric_summary = _aggregate(completed_for_metrics) if completed_for_metrics else {}
        complete = has_valid_comparison_results(ck.slots)
        out = {
            "run_id": args.run_id,
            "config_id": cfg_id,
            "created_at": datetime.now(UTC).isoformat(),
            "sealed": True,
            "sealed_path": str(SEALED_PATH),
            "sealed_sha256": sealed_sha,
            "freeze_manifest": str(freeze_path),
            "freeze_sha256": freeze_sha,
            "config_fingerprint": expected_fp,
            "prompt_id": PROMPT_ID,
            "prompt_sha256": p_sha,
            "verify_id": VERIFY_ID,
            "retrieval_mode": RETRIEVAL_MODE,
            "coverage_threshold": COVERAGE,
            "multi_hop_policy": POLICY,
            "bridge_rounds": BRIDGE_ROUNDS if experimental else 0,
            "experimental_passage_reader": experimental,
            "model_id": model_id,
            "git_commit": git_commit,
            "corpus": corpus,
            "slot_summary": slot_summary,
            "summary": metric_summary,
            "budget": ck.budget.to_dict(),
            "paused": ck.paused,
            "pause_reason": ck.pause_reason,
            "config_complete": complete,
            "sealed_test_evaluated": False,  # set on comparison only if fully done
            "results": per_q,
        }
        path = RESULTS_DIR / f"{args.run_id}__{cfg_id}.json"
        write_json(path, out)
        summaries.append(
            {
                "config_id": cfg_id,
                "slot_summary": slot_summary,
                "summary": metric_summary,
                "config_complete": complete,
                "path": str(path),
            }
        )
        config_slots[cfg_id] = ck.slots  # type: ignore[assignment]
        print(
            json.dumps(
                {
                    "config": cfg_id,
                    "slot_summary": slot_summary,
                    "config_complete": complete,
                    "paused": ck.paused,
                },
                indent=2,
            ),
            flush=True,
        )

    # Rebuild slot maps as QuestionSlot dicts for completeness helper
    from eval.sealed_infra import QuestionSlot

    slot_maps: dict[str, dict[str, QuestionSlot]] = {}
    for cfg_id in config_ids:
        ck_path = CHECKPOINT_DIR / f"{args.run_id}__{cfg_id}.json"
        if ck_path.is_file():
            slot_maps[cfg_id] = ConfigCheckpoint.from_dict(_load(ck_path)).slots

    complete = sealed_run_complete(slot_maps, required_config_ids=config_ids)
    comparison = {
        "run_id": args.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "sealed_sha256": sealed_sha,
        "freeze_sha256": freeze_sha,
        "n_questions_expected": len(question_ids),
        "question_ids": question_ids,
        "summaries": summaries,
        "sealed_complete": complete,
        "sealed_test_evaluated": complete,
        "note": (
            "sealed_test_evaluated is true only when every expected ID is "
            "completed or failed for all required configs and each has ≥1 completed."
        ),
    }
    cpath = RESULTS_DIR / f"{args.run_id}__comparison.json"
    write_json(cpath, comparison)
    print(
        json.dumps(
            {
                "wrote": str(cpath),
                "sealed_complete": complete,
                "sealed_test_evaluated": complete,
            },
            indent=2,
        ),
        flush=True,
    )
    if not complete:
        sys.exit(10)  # incomplete — not a crash; signals multi-day resume needed


if __name__ == "__main__":
    try:
        main()
    except SealedBudgetExhausted as exc:
        print(f"BUDGET: {exc}", file=sys.stderr)
        sys.exit(11)
    except SealedDriftError as exc:
        print(f"DRIFT: {exc}", file=sys.stderr)
        sys.exit(3)
