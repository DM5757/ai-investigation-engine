"""One-shot sealed evaluation for the frozen final candidate.

Requires:
  --confirm-sealed-unlock YES
  --freeze-manifest path to docs/evidence/final_candidate_freeze.md (or JSON)

Evaluates the frozen candidate and a frozen legacy baseline on the untouched
sealed split exactly once. Does not write back into tuning caches used for
development. After this run, do not modify the candidate based on sealed answers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_final_push import (  # noqa: E402
    COVERAGE,
    POLICY,
    PROMPT_ID,
    RETRIEVAL_MODE,
    TOP_K,
    VERIFY_ID,
    _aggregate,
    _from_reader,
    _score,
)
from scripts._phase6_common import ensure_dirs, neon_doc_counts, write_json  # noqa: E402

SEALED_PATH = ROOT / "eval" / "questions" / "phase_b_bench_v1_test_sealed.json"
RESULTS_DIR = ROOT / "eval" / "results"
CACHE_DIR = ROOT / "data" / "cache" / "sealed_final"
CHECKPOINT_DIR = ROOT / "data" / "checkpoints" / "sealed_final"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-sealed-unlock", type=str, default="")
    parser.add_argument(
        "--freeze-manifest",
        type=str,
        default=str(ROOT / "docs" / "evidence" / "final_candidate_freeze.md"),
    )
    parser.add_argument("--limit", type=int, default=0, help="0 = full sealed set")
    parser.add_argument("--pause-s", type=float, default=1.5)
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument(
        "--configs",
        default="sealed_candidate_soft,sealed_legacy",
    )
    parser.add_argument("--stop-after-llm-unavailable", type=int, default=5)
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

    sealed = _load(SEALED_PATH)
    questions = list(sealed.get("questions") or [])
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]

    from app.config import get_settings
    from app.deps import get_or_create_llm, reset_process_singletons
    from app.investigation.engine import InvestigationEngine
    from app.investigation.reader import (
        passages_from_retrieval_hits,
        read_passages,
    )
    from app.investigation.verify import MultiHopPolicy
    from eval.run_e0_reader import _resolve_gold_doc_ids
    from eval.run_eval import _build_doc_maps, _build_stack, _run_investigation
    from scripts._phase6_common import open_session

    settings = get_settings()
    object.__setattr__(settings, "experimental_passage_reader", False)
    object.__setattr__(settings, "reader_multi_hop_policy", POLICY)
    object.__setattr__(settings, "reader_coverage_threshold", COVERAGE)
    reset_process_singletons()
    session = open_session(settings)
    title_to, path_to, ext_to = _build_doc_maps(session)
    corpus = neon_doc_counts(settings)
    store, retriever, _ = _build_stack(settings, RETRIEVAL_MODE)
    llm = get_or_create_llm(settings)
    if llm is None:
        print("ERROR: no LLM", file=sys.stderr)
        sys.exit(1)
    engine = InvestigationEngine(
        retriever=retriever, store=store, llm=llm, settings=settings
    )
    engine.retriever.default_mode = RETRIEVAL_MODE  # type: ignore[assignment]

    run_id = args.run_id or datetime.now(UTC).strftime("sealed_%Y%m%dT%H%M%SZ")
    model_id = getattr(settings, "groq_model", "") or getattr(settings, "gemini_model", "")
    config_ids = [c.strip() for c in args.configs.split(",") if c.strip()]
    summaries: list[dict[str, Any]] = []

    for cfg_id in config_ids:
        ck_path = CHECKPOINT_DIR / f"{run_id}__{cfg_id}.json"
        per_q: list[dict[str, Any]] = []
        done: set[str] = set()
        if ck_path.exists():
            ck = _load(ck_path)
            per_q = list(ck.get("results") or [])
            done = {str(r["question_id"]) for r in per_q}

        consecutive_fail = 0
        print(f"SEALED config={cfg_id} n={len(questions)}", flush=True)
        for q in questions:
            qid = str(q["id"])
            if qid in done:
                continue
            gold_docs = _resolve_gold_doc_ids(q, title_to, path_to, ext_to)
            row: dict[str, Any] = {
                "question_id": qid,
                "question_type": q.get("question_type"),
                "hotpot_type": q.get("hotpot_type"),
                "gold_answer": q.get("gold_answer"),
                "gold_doc_ids": gold_docs,
                "gold_doc_titles": q.get("gold_doc_titles"),
            }
            try:
                if hasattr(llm, "budget"):
                    llm.budget.reset()
                t0 = time.perf_counter()
                if cfg_id == "sealed_legacy":
                    result = _run_investigation(
                        engine, str(q["question"]), gold_doc_ids=gold_docs
                    )
                    result["answer_text"] = result.get("answer_text") or ""
                    result["answer_supported"] = result.get("status") == "answered"
                    result["evidence_chain_ok"] = False
                else:
                    hits = retriever.retrieve(
                        str(q["question"]), k=TOP_K, mode=RETRIEVAL_MODE  # type: ignore[arg-type]
                    )
                    passages = passages_from_retrieval_hits(hits, max_n=TOP_K)
                    need_mh = len(q.get("gold_doc_titles") or []) >= 2
                    out = read_passages(
                        question=str(q["question"]),
                        passages=passages,
                        llm=llm,
                        require_multi_hop=need_mh,
                        policy=MultiHopPolicy.SOFT,
                        coverage_threshold=COVERAGE,
                    )
                    result = _from_reader(out, passages, t0=t0)
                    # Sealed-only cache (not shared with dev tuning).
                    key = hashlib.sha256(
                        f"{cfg_id}|{qid}|{VERIFY_ID}".encode()
                    ).hexdigest()
                    (CACHE_DIR / f"{key}.json").write_text(
                        json.dumps(
                            {
                                "question_id": qid,
                                "raw_model": out.raw_model,
                                "status": out.status,
                                "answer": out.answer,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                row.update(result)
                row["answer"] = _score(q, result)
                consecutive_fail = 0
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                row["error"] = err[:500]
                row["status"] = "error"
                print(f"  FAIL {qid}: {err[:160]}", flush=True)
                if any(
                    x in err.lower()
                    for x in ("quota", "rate", "unavailable", "429", "403")
                ):
                    consecutive_fail += 1
                    if consecutive_fail >= args.stop_after_llm_unavailable:
                        per_q.append(row)
                        break
            per_q.append(row)
            write_json(ck_path, {"results": per_q})
            time.sleep(max(0.0, args.pause_s))

        summary = _aggregate(per_q)
        out = {
            "run_id": run_id,
            "config_id": cfg_id,
            "created_at": datetime.now(UTC).isoformat(),
            "sealed": True,
            "sealed_path": str(SEALED_PATH),
            "sealed_sha256": _sha256_file(SEALED_PATH),
            "freeze_manifest": str(freeze_path),
            "freeze_sha256": _sha256_file(freeze_path),
            "retrieval_mode": RETRIEVAL_MODE,
            "policy": POLICY,
            "coverage_threshold": COVERAGE,
            "verify_id": VERIFY_ID,
            "prompt_id": PROMPT_ID,
            "model_id": model_id,
            "corpus": corpus,
            "summary": summary,
            "results": per_q,
            "sealed_test_evaluated": True,
        }
        path = RESULTS_DIR / f"{run_id}__{cfg_id}.json"
        write_json(path, out)
        summaries.append({"config_id": cfg_id, "summary": summary, "path": str(path)})
        print(json.dumps({"config": cfg_id, "summary": summary}, indent=2), flush=True)

    comparison = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "sealed_test_evaluated": True,
        "sealed_sha256": _sha256_file(SEALED_PATH),
        "n_questions": len(questions),
        "summaries": summaries,
        "latency_note": "p50/p95 in per-config summaries",
    }
    cpath = RESULTS_DIR / f"{run_id}__comparison.json"
    write_json(cpath, comparison)
    print(f"wrote {cpath}", flush=True)


if __name__ == "__main__":
    main()
