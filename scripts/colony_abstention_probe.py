"""Record scripted-LLM colony abstention against Neon/Qdrant."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.deps import (  # noqa: E402
    get_or_create_bm25,
    get_or_create_chunk_store,
    get_or_create_embedder,
    reset_process_singletons,
)
from app.investigation.engine import InvestigationEngine  # noqa: E402
from app.llm.scripted import ScriptedLLM, ScriptedResponse  # noqa: E402
from app.retrieval.hybrid import HybridRetriever  # noqa: E402
from app.schemas.evidence import UsageStats  # noqa: E402
from scripts._phase6_common import write_json  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "colony_abstention_scripted.json"


def main() -> int:
    reset_process_singletons()
    settings = get_settings().model_copy(update={"tau_relative": 0.35, "max_tool_rounds": 1})
    store = get_or_create_chunk_store(settings)
    embedder = get_or_create_embedder(settings)
    bm25 = get_or_create_bm25(settings)
    retriever = HybridRetriever(store, embedder, bm25, settings=settings)
    llm = ScriptedLLM(
        [
            ScriptedResponse(
                content=json.dumps(
                    {
                        "question_type": "factual",
                        "sub_questions": [
                            {
                                "id": "q1",
                                "text": "What happened to the Roanoke Colony?",
                                "depends_on": [],
                            }
                        ],
                        "expected_answer_shape": "short_paragraph",
                    }
                ),
                usage=UsageStats(calls=1),
            ),
            ScriptedResponse(content=None, tool_calls=[], usage=UsageStats(calls=1)),
        ]
    )
    eng = InvestigationEngine(retriever, store, llm=llm, settings=settings)
    question = "What happened to the Roanoke Colony, and why did it disappear?"
    result = eng.investigate(question)
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "question": question,
        "mode": "scripted_llm_against_neon_qdrant",
        "status": result.status,
        "n_claims": len(result.claims),
        "n_citations": len(result.citations),
        "abstention_reason": result.abstention_reason,
        "answer_preview": (result.answer or "")[:240],
        "note": (
            "Question-conditioned sufficiency abstains instead of citing airports "
            "when colony evidence is absent."
        ),
    }
    write_json(OUT, payload)
    print(json.dumps(payload, indent=2))
    return 0 if result.status == "insufficient" else 1


if __name__ == "__main__":
    raise SystemExit(main())
