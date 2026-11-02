"""Probe evidence-retention stages on a few multi-gold questions (eval-only).

Does not tune against held-out answers. Writes docs/evidence/phase_a_retention.json.
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

from eval.metrics import gold_coverage  # noqa: E402
from eval.run_eval import _build_doc_maps, _resolve_gold_doc_ids  # noqa: E402
from scripts._phase6_common import neon_doc_counts, write_json  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "phase_a_retention.json"
QUESTIONS = ROOT / "eval" / "questions" / "eval_set.json"


def main() -> None:
    from app.config import get_settings
    from app.deps import get_or_create_llm, reset_process_singletons
    from app.investigation.engine import InvestigationEngine
    from eval.run_eval import _build_stack
    from scripts._phase6_common import open_session

    settings = get_settings()
    object.__setattr__(settings, "eval_record_retention", True)
    reset_process_singletons()
    session = open_session(settings)
    title_to, path_to, ext_to = _build_doc_maps(session)
    payload = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    # Prefer multi-gold Hotpot questions from legacy test (diagnostic only).
    candidates = [
        q
        for q in payload["questions"]
        if q.get("split") == "test"
        and len(q.get("gold_doc_titles") or []) >= 2
        and q.get("question_type") in ("multi_hop", "multi_doc", "factual")
    ][:8]
    store, retriever, _ = _build_stack(settings, "hybrid_rerank")
    llm = get_or_create_llm(settings)
    engine = InvestigationEngine(
        retriever=retriever, store=store, llm=llm, settings=settings
    )
    engine.retriever.default_mode = "hybrid_rerank"  # type: ignore[assignment]

    rows: list[dict[str, Any]] = []
    stage_loss: dict[str, list[float]] = {}
    for q in candidates:
        gold = _resolve_gold_doc_ids(q, title_to, path_to, ext_to)
        ans = engine.investigate(str(q["question"]))
        retention = ans.retention or {"stages": []}
        cov_stages = []
        for stage in retention.get("stages") or []:
            cov = gold_coverage(stage.get("doc_ids") or [], gold)
            cov_stages.append(
                {
                    "stage": stage.get("stage"),
                    "n_docs": stage.get("n_docs"),
                    "n_items": stage.get("n_items"),
                    "titles": stage.get("titles") or [],
                    **cov,
                }
            )
            stage_loss.setdefault(str(stage.get("stage")), []).append(
                float(cov["recall"])
            )
        rows.append(
            {
                "question_id": q.get("id"),
                "question_type": q.get("question_type"),
                "status": ans.status,
                "n_gold": len(gold),
                "gold_titles": q.get("gold_doc_titles"),
                "stages": cov_stages,
            }
        )
        print(
            f"{q.get('id')}: status={ans.status} stages="
            f"{[(s['stage'], s['recall']) for s in cov_stages]}",
            flush=True,
        )

    summary = {
        stage: {
            "n": len(vals),
            "mean_gold_recall": sum(vals) / len(vals) if vals else 0.0,
            "mean_gold_loss": 1.0 - (sum(vals) / len(vals) if vals else 0.0),
        }
        for stage, vals in stage_loss.items()
    }
    write_json(
        OUT,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "mode": "hybrid_rerank",
            "corpus": neon_doc_counts(settings),
            "note": (
                "Diagnostic probe on legacy multi-gold test items. "
                "Gold labels used only after the engine returns."
            ),
            "stage_summary": summary,
            "cases": rows,
        },
    )
    print(f"wrote {OUT.as_posix()}", flush=True)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
