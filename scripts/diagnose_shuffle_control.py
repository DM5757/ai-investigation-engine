"""Diagnose Phase B shuffled-passage negative control failure."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    oracle = json.loads(
        (ROOT / "eval/results/e0_dev_v1__e0_oracle.json").read_text(encoding="utf-8")
    )
    shuf = json.loads(
        (ROOT / "eval/results/e0_dev_v1__e0_oracle_shuffle.json").read_text(
            encoding="utf-8"
        )
    )
    o = {
        r["question_id"]: r
        for r in oracle["results"]
        if not str(r["question_id"]).startswith("phaseb_robust")
    }
    s = {
        r["question_id"]: r
        for r in shuf["results"]
        if not str(r["question_id"]).startswith("phaseb_robust")
    }
    common = sorted(set(o) & set(s))
    same = sum(
        1
        for q in common
        if (o[q].get("answer_text") or "").strip().lower()
        == (s[q].get("answer_text") or "").strip().lower()
        and (o[q].get("answer_text") or "").strip()
    )
    both_ok = sum(
        1
        for q in common
        if float((o[q].get("answer") or {}).get("token_f1") or 0) >= 0.5
        and float((s[q].get("answer") or {}).get("token_f1") or 0) >= 0.5
    )
    print(f"n_common={len(common)} identical_answers={same} both_f1>=0.5={both_ok}")
    print(
        "CAUSE: e0_oracle_shuffle only permutes gold paragraph TEXTS among gold "
        "TITLES. All gold evidence remains in context; titles stay attached to "
        "passage objects. Cache is NOT reused for shuffle. High F1 is expected "
        "because supporting content was never removed."
    )
    for qid in common[:5]:
        r = s[qid]
        print("---", qid)
        print(" gold:", r.get("gold_answer"))
        print(" pred:", (r.get("answer_text") or "")[:100])
        print(
            " f1 o/s:",
            round(float((o[qid].get("answer") or {}).get("token_f1") or 0), 3),
            round(float((r.get("answer") or {}).get("token_f1") or 0), 3),
        )
        print(" titles:", r.get("passage_titles"))
        print(" supported:", r.get("answer_supported"), "shuffled:", r.get("shuffled_passages"))


if __name__ == "__main__":
    main()
