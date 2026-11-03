"""Offline re-verify of cached reader raw_model outputs (no LLM calls).

Applies current verify.py (paraphrase + cited-passage support + SOFT/STRICT)
to phase_c1 / phase_c / e0 caches. Development diagnostics only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.metrics import exact_match, mean, token_f1  # noqa: E402
from eval.negative_controls import CONTROL_EXPECT  # noqa: E402
from scripts._phase6_common import write_json  # noqa: E402

RESULTS_DIR = ROOT / "eval" / "results"
DEV_PATH = ROOT / "eval" / "questions" / "phase_b_bench_v1_dev.json"
ROBUST_PATH = ROOT / "eval" / "questions" / "phase_c_robustness_v1.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _index_questions() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in (DEV_PATH, ROBUST_PATH):
        if not path.is_file():
            continue
        payload = _load(path)
        for q in payload.get("questions") or []:
            out[str(q["id"])] = q
        for q in payload.get("robustness_questions") or []:
            out[str(q["id"])] = q
    return out


def _score(
    question: dict[str, Any] | None,
    result: dict[str, Any],
    *,
    control_id: str | None = None,
) -> dict[str, Any]:
    gold = str((question or {}).get("gold_answer") or "")
    pred = str(result.get("answer") or "")
    status = str(result.get("status") or "")
    supported = bool(result.get("answer_supported"))
    chain_ok = bool(result.get("evidence_chain_ok"))
    qtype = str((question or {}).get("question_type") or "")
    expect = CONTROL_EXPECT.get(control_id or "", {})
    must_abstain = bool(expect.get("must_abstain")) or qtype in (
        "unanswerable",
        "contradiction",
    ) or gold in ("INSUFFICIENT", "CONFLICTING")

    raw_em = 0.0 if must_abstain else exact_match(pred, gold)
    raw_f1 = 0.0 if must_abstain else token_f1(pred, gold)
    if status == "answered" and supported and chain_ok and not must_abstain:
        em, f1 = raw_em, raw_f1
    else:
        em, f1 = 0.0, 0.0

    scores: dict[str, Any] = {
        "exact_match": em,
        "token_f1": f1,
        "raw_exact_match": raw_em,
        "raw_token_f1": raw_f1,
        "answer_supported": 1.0 if supported else 0.0,
        "evidence_chain_ok": 1.0 if chain_ok else 0.0,
        "full_answered": 1.0 if status == "answered" else 0.0,
        "partial": 1.0 if status == "partial" else 0.0,
        "unsupported_full_answer": 1.0
        if status == "answered" and not (supported and chain_ok)
        else 0.0,
        "coverage": float(result.get("coverage") or 0.0),
    }
    if must_abstain:
        if status == "answered":
            ok = False
        elif status == "partial" and control_id == "missing_one_hop":
            ok = True
        else:
            ok = status in {"insufficient", "conflicting"}
        scores["correct_abstention"] = 1.0 if ok else 0.0
        scores["false_answer"] = 0.0 if ok else 1.0
    return scores


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    keys = [
        "exact_match",
        "token_f1",
        "raw_token_f1",
        "answer_supported",
        "evidence_chain_ok",
        "full_answered",
        "partial",
        "unsupported_full_answer",
        "correct_abstention",
        "false_answer",
        "coverage",
    ]
    out: dict[str, Any] = {"n": len(rows)}
    for k in keys:
        vals = [float(r["scores"][k]) for r in rows if k in r.get("scores", {})]
        if vals:
            out[k] = mean(vals)
    out["status_counts"] = {
        s: sum(1 for r in rows if r.get("status") == s)
        for s in sorted({str(r.get("status")) for r in rows})
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=str(ROOT / "data" / "cache" / "phase_c1_reader"),
    )
    parser.add_argument("--policy", choices=("soft", "strict"), default="soft")
    parser.add_argument("--coverage", type=float, default=0.65)
    parser.add_argument("--run-id", type=str, default="")
    args = parser.parse_args()

    from app.investigation.reader import ReaderPassage
    from app.investigation.verify import MultiHopPolicy, verify_structured_reader_output

    cache_dir = Path(args.cache_dir)
    qindex = _index_questions()
    policy = MultiHopPolicy(args.policy)
    rows: list[dict[str, Any]] = []

    for path in sorted(cache_dir.glob("*.json")):
        payload = _load(path)
        raw = payload.get("raw_model")
        passages_raw = payload.get("passages") or []
        if not isinstance(raw, dict) or not passages_raw:
            continue
        passages = [
            ReaderPassage(
                label=str(p.get("label") or ""),
                title=str(p.get("title") or ""),
                text=str(p.get("text") or ""),
                doc_id=p.get("doc_id"),
                chunk_id=p.get("chunk_id"),
            )
            for p in passages_raw
            if isinstance(p, dict)
        ]
        # Infer multi-hop from presence of ≥2 gold-like passages when unknown.
        require_mh = len(passages) >= 2
        verified = verify_structured_reader_output(
            raw,
            passages,
            require_multi_hop=require_mh,
            min_hops=2,
            policy=policy,
            coverage_threshold=args.coverage,
        )
        # Try to recover question id from sibling result files is hard; score
        # without gold when unknown (still useful for status/support rates).
        qid = str(payload.get("question_id") or path.stem)
        question = qindex.get(qid)
        control_id = None
        if question and question.get("negative_control"):
            control_id = str(question.get("control_id") or "")
        result = {
            "answer": verified.answer,
            "status": verified.status,
            "answer_supported": verified.answer_supported,
            "evidence_chain_ok": verified.evidence_chain_ok,
            "coverage": verified.coverage,
        }
        rows.append(
            {
                "cache_file": path.name,
                "question_id": qid,
                "status": verified.status,
                "answer": verified.answer,
                "answer_supported": verified.answer_supported,
                "evidence_chain_ok": verified.evidence_chain_ok,
                "coverage": verified.coverage,
                "unsupported_reasons": verified.unsupported_reasons,
                "scores": _score(question, result, control_id=control_id),
                "has_gold": question is not None and bool(question.get("gold_answer")),
            }
        )

    run_id = args.run_id or datetime.now(UTC).strftime(
        f"rescore_{args.policy}_%Y%m%dT%H%M%SZ"
    )
    with_gold = [r for r in rows if r["has_gold"]]
    out = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "cache_dir": str(cache_dir),
        "policy": args.policy,
        "coverage_threshold": args.coverage,
        "verify_id": "verify_final_v1",
        "n_cache_files": len(rows),
        "summary_all": _summarize(rows),
        "summary_with_gold": _summarize(with_gold),
        "sealed_test_evaluated": False,
        "note": (
            "Offline re-verify of cached raw_model; no new LLM calls. "
            "require_multi_hop inferred as len(passages)>=2 when question unknown."
        ),
        "results": rows,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{run_id}.json"
    write_json(path, out)
    print(
        json.dumps(
            {
                "n": len(rows),
                "summary_all": out["summary_all"],
                "summary_with_gold": out["summary_with_gold"],
            },
            indent=2,
        )
    )
    print(f"wrote {path}", flush=True)


if __name__ == "__main__":
    main()
