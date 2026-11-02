"""Re-score existing evaluation predictions with citation-stripped EM/token F1.

Does NOT re-run the model. Preserves original metrics under ``answer_legacy``
and writes corrected scores under ``answer``. Distinguishes scoring fixes from
model improvements.

Usage:
  uv run python scripts/rescore_eval_predictions.py \\
    --input eval/results/m7_test_adapt_v3__full_investigation.json
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

QUESTIONS_PATH = ROOT / "eval" / "questions" / "eval_set.json"


def _load_gold_answers(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for q in payload.get("questions") or []:
        qid = str(q.get("id") or "")
        if qid:
            out[qid] = q
    return out


def _rescore_row(row: dict[str, Any], gold_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    qmeta = gold_by_id.get(str(row.get("question_id") or ""), {})
    gold = str(row.get("gold_answer") or qmeta.get("gold_answer") or "")
    qtype = str(row.get("question_type") or qmeta.get("question_type") or "")
    pred = str(row.get("answer_text") or "")
    special = gold in ("INSUFFICIENT", "CONFLICTING") or qtype in (
        "unanswerable",
        "contradiction",
    )
    legacy = dict(row.get("answer") or {})
    # For unanswerable/contradiction, keep EM/F1 at 0 (status metrics matter).
    if special and not gold:
        gold = "INSUFFICIENT" if qtype == "unanswerable" else "CONFLICTING"
        special = True
    corrected = {
        "exact_match": 0.0 if special else exact_match(pred, gold, strip_citations=True),
        "token_f1": 0.0 if special else token_f1(pred, gold, strip_citations=True),
        "exact_match_legacy_with_cites": (
            0.0 if special else exact_match(pred, gold, strip_citations=False)
        ),
        "token_f1_legacy_with_cites": (
            0.0 if special else token_f1(pred, gold, strip_citations=False)
        ),
        "gold_answer": gold,
    }
    # Preserve citation metrics from original scoring.
    if "citation" in legacy:
        corrected["citation"] = legacy["citation"]
    for key in (
        "status_match",
        "correct_abstention",
        "soft_abstention",
        "false_answer_on_unanswerable",
        "contradiction_detected",
        "citation_f1_answered_only",
    ):
        if key in legacy:
            corrected[key] = legacy[key]
    out = dict(row)
    out["answer_legacy"] = legacy
    out["answer"] = corrected
    out["scoring_note"] = (
        "EM/token_f1 re-scored with citation markers stripped; "
        "predictions unchanged. Legacy scores kept in answer_legacy."
    )
    return out


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if "answer" in r and not r.get("error")]
    em = [float(r["answer"]["exact_match"]) for r in scored]
    f1 = [float(r["answer"]["token_f1"]) for r in scored]
    em_leg = [float(r["answer"].get("exact_match_legacy_with_cites", 0.0)) for r in scored]
    f1_leg = [float(r["answer"].get("token_f1_legacy_with_cites", 0.0)) for r in scored]
    cite = [
        float((r["answer"].get("citation") or {}).get("f1") or 0.0)
        for r in scored
        if r["answer"].get("citation") is not None
    ]
    return {
        "n_scored": len(scored),
        "exact_match": mean(em),
        "token_f1": mean(f1),
        "exact_match_legacy_with_cites": mean(em_leg),
        "token_f1_legacy_with_cites": mean(f1_leg),
        "citation_f1": mean(cite) if cite else None,
        "delta_token_f1_vs_legacy": mean(f1) - mean(f1_leg) if scored else 0.0,
        "delta_exact_match_vs_legacy": mean(em) - mean(em_leg) if scored else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "eval" / "results" / "m7_test_adapt_v3__full_investigation.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Default: <stem>__rescored_cite_strip.json beside input",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=QUESTIONS_PATH,
        help="Eval questions JSON used to recover gold answers",
    )
    args = parser.parse_args()
    src = args.input
    if not src.is_file():
        print(f"ERROR: missing {src}", file=sys.stderr)
        sys.exit(1)
    gold_by_id = _load_gold_answers(args.questions)
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = list(data.get("results") or [])
    rescored_rows = [_rescore_row(r, gold_by_id) for r in rows]
    summary = _aggregate(rescored_rows)
    out_path = args.output
    if out_path is None:
        out_path = src.with_name(f"{src.stem}__rescored_cite_strip.json")
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_artifact": str(src.as_posix()),
        "scoring_revision": "citation_strip_v1",
        "note": (
            "Predictions unchanged. EM/token F1 recomputed after stripping "
            "citation markers. This is a scoring correction, not a model improvement."
        ),
        "original_summary": data.get("summary"),
        "corrected_summary": summary,
        "config": data.get("config"),
        "results": rescored_rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {out_path.as_posix()} n={summary['n_scored']} "
        f"token_f1 {summary['token_f1_legacy_with_cites']:.4f} -> {summary['token_f1']:.4f} "
        f"(delta {summary['delta_token_f1_vs_legacy']:+.4f}) "
        f"EM {summary['exact_match_legacy_with_cites']:.4f} -> {summary['exact_match']:.4f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
