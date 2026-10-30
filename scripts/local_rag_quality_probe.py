"""Local investigation probe against Neon/Qdrant (no Render cold-start)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.deps import (  # noqa: E402
    get_or_create_bm25,
    get_or_create_chunk_store,
    get_or_create_embedder,
    get_or_create_llm,
)
from app.investigation.engine import InvestigationEngine  # noqa: E402
from app.retrieval.hybrid import HybridRetriever  # noqa: E402
from scripts._phase6_common import write_json  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "local_rag_quality_probe.json"

CASES = [
    {
        "id": "roanoke_colony",
        "question": "What happened to the Roanoke Colony, and why did it disappear?",
        "expect_status_in": ["insufficient", "llm_unavailable"],
    },
    {
        "id": "roanoke_airport",
        "question": "What is Roanoke–Blacksburg Regional Airport, and where is it located?",
        "expect_status_in": ["answered", "partial", "llm_unavailable"],
    },
]


def main() -> int:
    from app.deps import reset_process_singletons

    reset_process_singletons()
    settings = get_settings().model_copy(
        update={"llm_budget_wall_clock_s": 600.0, "tau_relative": 0.35}
    )

    store = get_or_create_chunk_store(settings)
    embedder = get_or_create_embedder(settings)
    bm25 = get_or_create_bm25(settings)
    llm = get_or_create_llm(settings)
    if llm is not None and hasattr(llm, "budget"):
        llm.budget.max_calls = settings.llm_budget_max_calls
        llm.budget.max_tokens = settings.llm_budget_max_tokens
        llm.budget.max_wall_clock_s = 600.0
        llm.budget.reset()

    retriever = HybridRetriever(store, embedder, bm25, settings=settings)
    engine = InvestigationEngine(retriever, store, llm=llm, settings=settings)

    cases_out: list[dict[str, Any]] = []
    for case in CASES:
        result = engine.investigate(case["question"])
        titles = []
        for cite in result.citations[:8]:
            titles.append(cite.doc_id)
        row = {
            "id": case["id"],
            "status": result.status,
            "degraded": result.degraded,
            "n_citations": len(result.citations),
            "n_claims": len(result.claims),
            "n_evidence_preview": len(result.evidence_preview),
            "usage_calls": result.usage.calls,
            "abstention_reason": result.abstention_reason,
            "answer_preview": (result.answer or "")[:500],
            "citation_doc_ids": titles,
            "expect_status_in": case["expect_status_in"],
            "ok": result.status in case["expect_status_in"],
        }
        # Stronger check for colony: must not invent an answered dump of airports
        if case["id"] == "roanoke_colony" and result.status == "answered":
            row["ok"] = False
            row["note"] = "colony question must not be answered without colony evidence"
        if case["id"] == "roanoke_airport" and result.status == "answered":
            row["ok"] = len(result.citations) <= 3 and bool(result.answer)
        cases_out.append(row)
        print(
            f"{case['id']}: status={row['status']} cites={row['n_citations']} "
            f"calls={row['usage_calls']} ok={row['ok']}"
        )

    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "llm_configured": llm is not None,
        "cases": cases_out,
        "ok": all(c["ok"] for c in cases_out),
    }
    write_json(OUT, payload)
    print(f"wrote {OUT} ok={payload['ok']}")
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
