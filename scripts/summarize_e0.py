"""Summarize Phase B E0 comparison + paired Hotpot-only metrics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "e0_dev_v1"
    cmp_path = ROOT / "eval" / "results" / f"{run_id}__comparison.json"
    cmp = json.loads(cmp_path.read_text(encoding="utf-8"))
    for s in cmp["summaries"]:
        sm = s["summary"]
        print(
            f"{s['config_id']}: n={sm['n_scored']}/{sm['n_attempted']} "
            f"F1={sm['token_f1']:.3f} EM={sm['exact_match']:.3f} "
            f"supp={sm['answer_supported_rate']:.3f} "
            f"cite={sm.get('citation_f1')} multi={sm.get('multi_hop_all_gold_cited')} "
            f"retr_ag={sm.get('retrieval_all_gold_at_k')} "
            f"abst={sm.get('correct_abstention_rate')} "
            f"false={sm.get('false_answer_on_unanswerable')} "
            f"contra={sm.get('contradiction_detection_rate')} "
            f"fail={sm['n_provider_failures']} tok={sm['mean_tokens']:.0f}"
        )

    # Paired Hotpot-only on questions present in oracle+raw+legacy with no error.
    configs = ["e0_oracle", "e0_raw", "e0_legacy"]
    rows: dict[str, dict[str, dict]] = {}
    for cfg in configs:
        path = ROOT / "eval" / "results" / f"{run_id}__{cfg}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data["results"]:
            qid = r["question_id"]
            if str(qid).startswith("phaseb_robust"):
                continue
            if r.get("error"):
                continue
            rows.setdefault(qid, {})[cfg] = r
    common = [qid for qid, m in rows.items() if all(c in m for c in configs)]
    print(f"\npaired hotpot n={len(common)}")
    for cfg in configs:
        f1s = [float((rows[q][cfg].get("answer") or {}).get("token_f1") or 0) for q in common]
        ems = [float((rows[q][cfg].get("answer") or {}).get("exact_match") or 0) for q in common]
        supp = [
            float((rows[q][cfg].get("answer") or {}).get("answer_supported") or 0) for q in common
        ]
        cite = [
            float(((rows[q][cfg].get("answer") or {}).get("citation") or {}).get("f1") or 0)
            for q in common
            if (rows[q][cfg].get("answer") or {}).get("citation") is not None
        ]
        multi = [
            float((rows[q][cfg].get("answer") or {}).get("multi_hop_all_gold_cited") or 0)
            for q in common
            if "multi_hop_all_gold_cited" in (rows[q][cfg].get("answer") or {})
        ]
        print(
            f"  {cfg}: F1={sum(f1s)/len(f1s):.3f} EM={sum(ems)/len(ems):.3f} "
            f"supp={sum(supp)/len(supp):.3f} "
            f"cite={sum(cite)/len(cite) if cite else None} "
            f"multi={sum(multi)/len(multi) if multi else None}"
        )

    # Robustness slice
    print("\nrobustness:")
    for cfg in ["e0_oracle", "e0_raw", "e0_legacy"]:
        path = ROOT / "eval" / "results" / f"{run_id}__{cfg}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        rob = [r for r in data["results"] if str(r["question_id"]).startswith("phaseb_robust")]
        for r in rob:
            ans = r.get("answer") or {}
            print(
                f"  {cfg} {r['question_id']}: status={r.get('status')} "
                f"abst={ans.get('correct_abstention')} "
                f"false={ans.get('false_answer_on_unanswerable')} "
                f"contra={ans.get('contradiction_detected')} "
                f"f1={ans.get('token_f1')}"
            )


if __name__ == "__main__":
    main()
