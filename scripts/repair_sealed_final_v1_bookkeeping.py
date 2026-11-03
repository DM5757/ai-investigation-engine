"""One-shot repair for sealed_final_v1 bookkeeping (no LLM calls).

Reclassifies known llm_unavailable candidate slots from completed → failed,
deletes only their poisoned cache entries, inspects legacy for similar
invalid statuses, and writes an incomplete/inconclusive status artifact.

Does not resume evaluation or alter genuine completions.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.sealed_infra import (  # noqa: E402
    QuestionSlot,
    is_infra_failure_result,
    slot_counts,
)
from scripts._phase6_common import write_json  # noqa: E402

CK_DIR = ROOT / "data" / "checkpoints" / "sealed_final"
CACHE_DIR = ROOT / "data" / "cache" / "sealed_final"
RESULTS_DIR = ROOT / "eval" / "results"
STATUS_PATH = ROOT / "docs" / "evidence" / "sealed_final_v1_status.md"

KNOWN_BAD_CANDIDATE_IDS = (
    "phaseb_hotpot_5ac3caa15542995ef918c23a",
    "phaseb_hotpot_5a7c97e15542990527d554db",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _repair_candidate(ck: dict[str, Any]) -> dict[str, Any]:
    slots = ck.get("slots") or {}
    repaired: list[str] = []
    for qid in KNOWN_BAD_CANDIDATE_IDS:
        slot = slots.get(qid)
        if not isinstance(slot, dict):
            continue
        result = slot.get("result") or {}
        if not is_infra_failure_result(result) and result.get("status") != "llm_unavailable":
            continue
        err = str(
            result.get("abstention_reason")
            or result.get("status")
            or "llm_unavailable"
        )
        # Preserve prior result payload under audit key; clear as completion.
        slots[qid] = QuestionSlot(
            question_id=qid,
            status="failed",
            error=err[:500],
            result={
                "audit_prior_invalid_completion": result,
                "status": "error",
                "reclassified_from": "completed",
                "reclassified_reason": "llm_unavailable_not_a_valid_completion",
            },
            updated_at=datetime.now(UTC).isoformat(),
        ).to_dict()
        repaired.append(qid)
    ck["slots"] = slots
    ck["slot_counts"] = slot_counts(
        {k: QuestionSlot.from_dict(v) for k, v in slots.items()}
    )
    ck["bookkeeping_repair"] = {
        "repaired_at": datetime.now(UTC).isoformat(),
        "reclassified_to_failed": repaired,
        "note": (
            "llm_unavailable outcomes are infrastructure failures, not valid "
            "model completions. Genuine completions left untouched."
        ),
    }
    ck["paused"] = True
    ck["pause_reason"] = "operator_stop_incomplete_sealed"
    ck["updated_at"] = datetime.now(UTC).isoformat()
    return {"repaired": repaired, "slot_counts": ck["slot_counts"]}


def _inspect_legacy(ck: dict[str, Any]) -> dict[str, Any]:
    slots = ck.get("slots") or {}
    infra: list[str] = []
    zero_llm_ok: list[str] = []
    for qid, slot in slots.items():
        if not isinstance(slot, dict) or slot.get("status") != "completed":
            continue
        result = slot.get("result") or {}
        if is_infra_failure_result(result):
            infra.append(qid)
        elif int(result.get("llm_calls") or 0) == 0:
            # Deterministic legacy path can be a valid completion.
            zero_llm_ok.append(qid)
    return {
        "n_completed": sum(
            1 for s in slots.values() if isinstance(s, dict) and s.get("status") == "completed"
        ),
        "infra_failure_marked_completed": infra,
        "deterministic_zero_llm_completed": len(zero_llm_ok),
        "note": (
            "Zero-LLM legacy answered/insufficient outcomes are retained as "
            "valid deterministic completions unless status is llm_unavailable."
        ),
    }


def _purge_poisoned_caches(question_ids: list[str]) -> list[str]:
    removed: list[str] = []
    if not CACHE_DIR.is_dir():
        return removed
    for path in CACHE_DIR.glob("*.json"):
        data = _load(path)
        qid = str(data.get("question_id") or "")
        result = data.get("result") or {}
        candidate_cache = data.get("config_id") == "sealed_candidate_soft"
        known_bad = qid in question_ids
        poisoned = is_infra_failure_result(result)
        if (known_bad or poisoned) and (candidate_cache or known_bad):
            path.unlink(missing_ok=True)
            removed.append(path.name)
    return removed


def main() -> None:
    cand_path = CK_DIR / "sealed_final_v1__sealed_candidate_soft.json"
    leg_path = CK_DIR / "sealed_final_v1__sealed_legacy.json"
    if not cand_path.is_file():
        print(f"ERROR: missing {cand_path}", file=sys.stderr)
        sys.exit(1)

    cand = _load(cand_path)
    repair_info = _repair_candidate(cand)
    write_json(cand_path, cand)

    legacy_info: dict[str, Any] = {}
    if leg_path.is_file():
        leg = _load(leg_path)
        legacy_info = _inspect_legacy(leg)
        leg["bookkeeping_inspection"] = {
            **legacy_info,
            "inspected_at": datetime.now(UTC).isoformat(),
            "reclassified": [],
        }
        # Only reclassify true infra failures on legacy if any.
        slots = leg.get("slots") or {}
        for qid in list(legacy_info.get("infra_failure_marked_completed") or []):
            slot = slots.get(qid) or {}
            result = slot.get("result") or {}
            err = str(result.get("abstention_reason") or result.get("status") or "infra")
            slots[qid] = QuestionSlot(
                question_id=qid,
                status="failed",
                error=err[:500],
                result={
                    "audit_prior_invalid_completion": result,
                    "status": "error",
                    "reclassified_from": "completed",
                    "reclassified_reason": "infra_failure_not_a_valid_completion",
                },
                updated_at=datetime.now(UTC).isoformat(),
            ).to_dict()
        leg["slots"] = slots
        leg["slot_counts"] = slot_counts(
            {k: QuestionSlot.from_dict(v) for k, v in slots.items()}
        )
        leg["paused"] = True
        leg["pause_reason"] = "operator_stop_incomplete_sealed"
        write_json(leg_path, leg)
        legacy_info["slot_counts_after"] = leg["slot_counts"]

    removed = _purge_poisoned_caches(list(KNOWN_BAD_CANDIDATE_IDS))

    # Annotate result JSON if present (do not invent metrics).
    res_path = RESULTS_DIR / "sealed_final_v1__sealed_candidate_soft.json"
    if res_path.is_file():
        res = _load(res_path)
        res["bookkeeping_repair"] = repair_info
        res["sealed_complete"] = False
        res["sealed_test_evaluated"] = False
        res["inconclusive"] = True
        res["note"] = (
            "Incomplete sealed run. Not a final accuracy result. "
            "Two llm_unavailable slots reclassified to failed."
        )
        write_json(res_path, res)

    cmp_path = RESULTS_DIR / "sealed_final_v1__comparison.json"
    comparison = {
        "run_id": "sealed_final_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "sealed_complete": False,
        "sealed_test_evaluated": False,
        "inconclusive": True,
        "candidate_repair": repair_info,
        "legacy_inspection": legacy_info,
        "poisoned_caches_removed": removed,
        "status": "incomplete_inconclusive",
        "note": (
            "Sealed benchmark interrupted by provider quotas. "
            "Do not cite as final accuracy. Evaluation not resumed."
        ),
    }
    write_json(cmp_path, comparison)

    STATUS_PATH.write_text(
        "\n".join(
            [
                "# Sealed evaluation status — `sealed_final_v1`",
                "",
                f"**Updated:** {datetime.now(UTC).date().isoformat()}",
                "**Status:** incomplete / inconclusive — **not a final accuracy result**",
                "",
                "## What happened",
                "",
                "- Stopped after Groq `daily_quota` and Gemini `rate_limit_rpm`.",
                "- Candidate: **38** genuine LLM outcomes; **2** `llm_unavailable`",
                "  reclassified from completed → **failed**.",
                "- Legacy checkpoint retained; zero-LLM deterministic outcomes kept.",
                "- Remaining sealed IDs stay **pending**. Evaluation was **not** resumed.",
                "",
                "## Bookkeeping repair",
                "",
                f"- Reclassified IDs: `{', '.join(KNOWN_BAD_CANDIDATE_IDS)}`",
                f"- Poisoned cache files removed: {len(removed)}",
                "- Harness treats future `llm_unavailable` as failures, not completions.",
                "",
                "## Production",
                "",
                "- Experimental passage reader remains **disabled** by default.",
                "- Do not advertise incomplete sealed results as production quality.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidate": repair_info,
                "legacy": legacy_info,
                "caches_removed": removed,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
