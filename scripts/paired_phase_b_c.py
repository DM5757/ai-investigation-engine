"""Paired Phase B vs Phase C comparison on identical development question IDs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.metrics import mean  # noqa: E402

OUT = ROOT / "eval" / "results" / "phase_c1_paired_b_vs_c.json"


def _load_rows(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for r in data.get("results") or []:
        qid = str(r.get("question_id") or "")
        if not qid or qid.startswith("phasec_") or qid.startswith("phaseb_robust"):
            continue
        if r.get("error") or r.get("status") == "llm_unavailable":
            continue
        if str(r.get("origin") or "").startswith("synthetic"):
            continue
        out[qid] = r
    return out


def _cite_f1(row: dict[str, Any]) -> float | None:
    c = (row.get("answer") or {}).get("citation")
    if not isinstance(c, dict):
        return None
    return float(c.get("f1") or 0.0)


def _multi(row: dict[str, Any]) -> float | None:
    a = row.get("answer") or {}
    if "multi_hop_all_gold_cited" not in a:
        return None
    return float(a.get("multi_hop_all_gold_cited") or 0.0)


def summarize(rows_b: dict[str, dict], rows_c: dict[str, dict], common: list[str]) -> dict:
    def collect(getter):
        vals = []
        for q in common:
            v = getter(rows_b[q], rows_c[q])
            if v is not None:
                vals.append(v)
        return vals

    b_f1 = [float((rows_b[q].get("answer") or {}).get("token_f1") or 0) for q in common]
    c_f1 = [float((rows_c[q].get("answer") or {}).get("token_f1") or 0) for q in common]
    b_em = [float((rows_b[q].get("answer") or {}).get("exact_match") or 0) for q in common]
    c_em = [float((rows_c[q].get("answer") or {}).get("exact_match") or 0) for q in common]
    b_sup = [float((rows_b[q].get("answer") or {}).get("answer_supported") or 0) for q in common]
    c_sup = [float((rows_c[q].get("answer") or {}).get("answer_supported") or 0) for q in common]

    b_cite = [_cite_f1(rows_b[q]) for q in common]
    c_cite = [_cite_f1(rows_c[q]) for q in common]
    b_cite_v = [x for x in b_cite if x is not None]
    c_cite_v = [x for x in c_cite if x is not None]
    b_multi = [_multi(rows_b[q]) for q in common]
    c_multi = [_multi(rows_c[q]) for q in common]
    b_multi_v = [x for x in b_multi if x is not None]
    c_multi_v = [x for x in c_multi if x is not None]

    improved = sum(1 for i, q in enumerate(common) if c_f1[i] > b_f1[i] + 1e-9)
    regressed = sum(1 for i, q in enumerate(common) if c_f1[i] + 1e-9 < b_f1[i])
    b_ans_ok = sum(
        1
        for q in common
        if float((rows_b[q].get("answer") or {}).get("token_f1") or 0) >= 0.5
    )
    c_abst_when_b_ok = []
    for q in common:
        bf = float((rows_b[q].get("answer") or {}).get("token_f1") or 0)
        cs = str(rows_c[q].get("status") or "")
        if bf >= 0.5 and cs in {"insufficient", "partial", "conflicting"}:
            c_abst_when_b_ok.append(q)

    return {
        "n_common": len(common),
        "phase_b": {
            "token_f1": mean(b_f1),
            "exact_match": mean(b_em),
            "answer_supported": mean(b_sup),
            "citation_f1": mean(b_cite_v) if b_cite_v else None,
            "multi_hop_all_gold_cited": mean(b_multi_v) if b_multi_v else None,
            "n_f1_ge_0.5": b_ans_ok,
        },
        "phase_c": {
            "token_f1": mean(c_f1),
            "exact_match": mean(c_em),
            "answer_supported": mean(c_sup),
            "citation_f1": mean(c_cite_v) if c_cite_v else None,
            "multi_hop_all_gold_cited": mean(c_multi_v) if c_multi_v else None,
            "status_counts": {
                s: sum(1 for q in common if str(rows_c[q].get("status")) == s)
                for s in sorted({str(rows_c[q].get("status")) for q in common})
            },
        },
        "deltas": {
            "token_f1": mean(c_f1) - mean(b_f1),
            "exact_match": mean(c_em) - mean(b_em),
            "n_improved_f1": improved,
            "n_regressed_f1": regressed,
            "n_b_ok_c_abstain_or_partial": len(c_abst_when_b_ok),
            "b_ok_c_abstain_ids": c_abst_when_b_ok,
        },
    }


def main() -> None:
    pairs = [
        (
            "oracle",
            ROOT / "eval/results/e0_dev_v1__e0_oracle.json",
            ROOT / "eval/results/phasec_ab_v1__c_oracle.json",
        ),
        (
            "raw",
            ROOT / "eval/results/e0_dev_v1__e0_raw.json",
            ROOT / "eval/results/phasec_ab_v1__c_raw.json",
        ),
        (
            "legacy",
            ROOT / "eval/results/e0_dev_v1__e0_legacy.json",
            ROOT / "eval/results/phasec_ab_v1__c_legacy.json",
        ),
    ]
    report: dict[str, Any] = {"pairs": {}}
    for name, pb, pc in pairs:
        if not pb.is_file() or not pc.is_file():
            report["pairs"][name] = {"error": "missing files"}
            continue
        rows_b = _load_rows(pb)
        rows_c = _load_rows(pc)
        common = sorted(set(rows_b) & set(rows_c))
        report["pairs"][name] = summarize(rows_b, rows_c, common)
        print(
            f"{name}: n={len(common)} "
            f"B_F1={report['pairs'][name]['phase_b']['token_f1']:.3f} "
            f"C_F1={report['pairs'][name]['phase_c']['token_f1']:.3f} "
            f"delta={report['pairs'][name]['deltas']['token_f1']:.3f} "
            f"B_multi={report['pairs'][name]['phase_b']['multi_hop_all_gold_cited']} "
            f"C_multi={report['pairs'][name]['phase_c']['multi_hop_all_gold_cited']} "
            f"regress={report['pairs'][name]['deltas']['n_regressed_f1']} "
            f"b_ok_c_abst={report['pairs'][name]['deltas']['n_b_ok_c_abstain_or_partial']}"
        )

    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
