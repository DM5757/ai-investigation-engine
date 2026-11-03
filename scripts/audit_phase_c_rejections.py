"""Audit Phase B-correct / Phase C-abstain cases on development Hotpot IDs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "results" / "phase_c1_rejection_audit.json"


def _load(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for r in data.get("results") or []:
        qid = str(r.get("question_id") or "")
        if not qid.startswith("phaseb_hotpot"):
            continue
        if r.get("error") or r.get("status") == "llm_unavailable":
            continue
        out[qid] = r
    return out


def classify(row_b: dict[str, Any], row_c: dict[str, Any]) -> dict[str, Any]:
    reasons = [str(x) for x in (row_c.get("unsupported_reasons") or [])]
    status = str(row_c.get("status") or "")
    b_f1 = float((row_b.get("answer") or {}).get("token_f1") or 0)
    c_f1 = float((row_c.get("answer") or {}).get("token_f1") or 0)
    cats: list[str] = []

    if any(r.startswith("incomplete_evidence_chain") for r in reasons):
        cats.append("missing_required_hop_or_cite")
    if any(r.startswith("answer_not_entailed:answer_token_coverage") for r in reasons):
        m = re.search(r"coverage=([0-9.]+)", " ".join(reasons))
        cov = float(m.group(1)) if m else None
        if cov is not None and cov >= 0.60:
            cats.append("overly_restrictive_coverage_threshold")
        else:
            cats.append("answer_not_entailed_low_coverage")
    if any(r.startswith("quote_mismatch") for r in reasons):
        cats.append("quote_mismatch")
    if any(r.startswith("invalid_label") for r in reasons):
        cats.append("invalid_source_label")
    if any(r == "answerable_without_valid_quotes" for r in reasons):
        cats.append("missing_citation_despite_claim")
    if status == "insufficient" and not reasons:
        cats.append("model_abstained_cleanly")
    if not cats:
        cats.append("other")

    # Heuristic: if B answer text appears in C passage titles context was available
    # and C had quotes but rejected on coverage → verification mistake candidate.
    verif_mistake = "overly_restrictive_coverage_threshold" in cats or (
        "quote_mismatch" in cats and b_f1 >= 0.8
    )
    model_mistake = (
        "missing_required_hop_or_cite" in cats and status == "insufficient"
    ) or "answer_not_entailed_low_coverage" in cats

    return {
        "question_id": row_c.get("question_id"),
        "gold": row_c.get("gold_answer"),
        "b_pred": row_b.get("answer_text"),
        "c_pred": row_c.get("answer_text"),
        "b_f1": b_f1,
        "c_f1": c_f1,
        "b_status": row_b.get("status"),
        "c_status": status,
        "reasons": reasons,
        "categories": cats,
        "likely_verification_mistake": verif_mistake,
        "likely_model_or_chain_gap": model_mistake,
        "missing_info": row_c.get("missing_info"),
        "n_passages": row_c.get("n_passages"),
        "n_citations": len(row_c.get("citations") or []),
    }


def main() -> None:
    report: dict[str, Any] = {"configs": {}}
    for name, pb, pc in (
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
    ):
        rows_b = _load(pb)
        rows_c = _load(pc)
        cases = []
        for qid in sorted(set(rows_b) & set(rows_c)):
            bf = float((rows_b[qid].get("answer") or {}).get("token_f1") or 0)
            cs = str(rows_c[qid].get("status") or "")
            if bf >= 0.5 and cs in {"insufficient", "partial", "conflicting"}:
                cases.append(classify(rows_b[qid], rows_c[qid]))
        cat_counts: dict[str, int] = {}
        for c in cases:
            for cat in c["categories"]:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        report["configs"][name] = {
            "n_cases": len(cases),
            "category_counts": cat_counts,
            "n_likely_verification_mistake": sum(
                1 for c in cases if c["likely_verification_mistake"]
            ),
            "n_likely_model_or_chain_gap": sum(
                1 for c in cases if c["likely_model_or_chain_gap"]
            ),
            "cases": cases,
        }
        print(
            f"{name}: n={len(cases)} cats={cat_counts} "
            f"verif_mistakes~{report['configs'][name]['n_likely_verification_mistake']} "
            f"model/chain~{report['configs'][name]['n_likely_model_or_chain_gap']}"
        )

    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
