"""Focused contradiction / abstention smoke against indexed synthetic evidence.

Uses real Neon+Qdrant corpus (synthetic docs already ingested). Bounded LLM usage.
Does not acquire the bulk-ingest lock.

Usage:
  uv run python scripts/behavioral_rag_smoke.py --no-llm
  uv run python scripts/behavioral_rag_smoke.py --pause-s 3
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

from app.config import get_settings  # noqa: E402
from app.deps import get_or_create_llm, reset_process_singletons  # noqa: E402
from app.investigation.contradictions import candidate_conflicts  # noqa: E402
from app.investigation.engine import InvestigationEngine  # noqa: E402
from app.investigation.sufficiency import assess_sufficiency  # noqa: E402
from app.schemas.evidence import Claim  # noqa: E402
from eval.run_eval import _build_stack  # noqa: E402
from scripts._phase6_common import (  # noqa: E402
    ensure_dirs,
    neon_doc_counts,
    write_json,
)

EVIDENCE = ROOT / "docs" / "evidence" / "behavioral_rag_smoke.json"
QUESTIONS = ROOT / "eval" / "questions" / "eval_set.json"


def _load_targets(limit: int) -> list[dict[str, Any]]:
    payload = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    wanted = {"contradiction", "unanswerable"}
    rows = [q for q in payload["questions"] if q.get("question_type") in wanted]
    if limit > 0:
        return rows[:limit]
    return rows


def _planted_claim_fixture() -> dict[str, Any]:
    """Deterministic unit-style checks independent of corpus/LLM."""
    agree = [
        Claim(
            claim_id="a1",
            subject="PaymentService",
            attribute="march_status",
            value="disrupted",
            doc_id="doc_a",
            chunk_id="c1",
            quote="disrupted",
            verified=True,
        ),
        Claim(
            claim_id="a2",
            subject="PaymentService",
            attribute="march_status",
            value="disrupted",
            doc_id="doc_b",
            chunk_id="c2",
            quote="disrupted",
            verified=True,
        ),
    ]
    conflict = [
        Claim(
            claim_id="b1",
            subject="PaymentService",
            attribute="march_status",
            value="disrupted after auth-gateway deploy",
            doc_id="doc_a",
            chunk_id="c1",
            quote="disrupted after auth-gateway deploy",
            verified=True,
        ),
        Claim(
            claim_id="b2",
            subject="PaymentService",
            attribute="march_status",
            value="zero incidents in March",
            doc_id="doc_b",
            chunk_id="c2",
            quote="zero incidents in March",
            verified=True,
        ),
    ]
    c_ok = candidate_conflicts(agree)
    c_bad = candidate_conflicts(conflict)
    s_empty, r_empty = assess_sufficiency(
        verified_claims=[], conflicts=[], question="unknown marker ZZZ-NONE"
    )
    s_conf, r_conf = assess_sufficiency(
        verified_claims=conflict, conflicts=c_bad, question="how long outage?"
    )
    return {
        "agree_conflicts": len(c_ok),
        "disagree_conflicts": len(c_bad),
        "empty_status": s_empty,
        "empty_reason": r_empty,
        "conflict_status": s_conf,
        "conflict_reason": r_conf,
        "pass": (
            len(c_ok) == 0
            and len(c_bad) >= 1
            and s_empty == "insufficient"
            and s_conf == "conflicting"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pause-s", type=float, default=2.0)
    args = parser.parse_args()

    ensure_dirs()
    settings = get_settings()
    reset_process_singletons()
    counts = neon_doc_counts(settings)
    targets = _load_targets(args.limit)
    out: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "corpus": counts,
        "deterministic_gate": _planted_claim_fixture(),
        "targets": [q["id"] for q in targets],
    }

    if args.no_llm:
        write_json(EVIDENCE, out)
        print(
            json.dumps(
                {"wrote": str(EVIDENCE), "llm": False, **out["deterministic_gate"]},
                indent=2,
            )
        )
        return

    store, retriever, _embedder = _build_stack(settings, "hybrid_rrf")
    llm = get_or_create_llm(settings)
    if llm is None:
        out["llm_error"] = "no providers configured"
        write_json(EVIDENCE, out)
        print(json.dumps(out, indent=2))
        return

    engine = InvestigationEngine(
        retriever=retriever, store=store, llm=llm, settings=settings
    )
    cases: list[dict[str, Any]] = []
    for q in targets:
        if hasattr(llm, "budget"):
            llm.budget.reset()
        t0 = time.perf_counter()
        try:
            ans = engine.investigate(str(q["question"]))
            cases.append(
                {
                    "id": q["id"],
                    "type": q.get("question_type"),
                    "status": ans.status,
                    "expected_status": q.get("expected_status"),
                    "n_conflicts": len(ans.conflicts or []),
                    "n_citations": len(ans.citations or []),
                    "abstention_reason": ans.abstention_reason,
                    "llm_calls": ans.usage.calls if ans.usage else 0,
                    "latency_s": round(time.perf_counter() - t0, 3),
                    "answer_preview": (ans.answer or "")[:240],
                    "provider_limit_likely": ans.status == "llm_unavailable",
                }
            )
        except Exception as exc:  # noqa: BLE001
            cases.append(
                {
                    "id": q["id"],
                    "type": q.get("question_type"),
                    "error": str(exc)[:300],
                    "latency_s": round(time.perf_counter() - t0, 3),
                }
            )
        if args.pause_s > 0:
            time.sleep(args.pause_s)

    out["llm_cases"] = cases
    write_json(EVIDENCE, out)
    print(
        json.dumps(
            {
                "wrote": str(EVIDENCE),
                "deterministic_pass": out["deterministic_gate"]["pass"],
                "n_llm": len(cases),
                "statuses": {
                    c.get("status") or "error": 1
                    for c in cases  # placeholder; printed fully below
                },
                "cases": [
                    {
                        "id": c.get("id"),
                        "type": c.get("type"),
                        "status": c.get("status"),
                        "expected": c.get("expected_status"),
                        "conflicts": c.get("n_conflicts"),
                        "llm_calls": c.get("llm_calls"),
                    }
                    for c in cases
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
