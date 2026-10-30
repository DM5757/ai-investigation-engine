"""Degraded evidence previews must not promote unrelated weak matches."""

from __future__ import annotations

from app.config import Settings
from app.investigation.engine import InvestigationEngine
from app.investigation.tools import ToolExecutor
from app.investigation.trace import TraceRecorder
from app.retrieval.types import RetrievalHit, ScoredChunk
from app.schemas.evidence import UsageStats


class _DummyStore:
    def get_payloads(self, _ids: list[str]) -> dict:
        return {}


class _DummyRetriever:
    default_mode = "hybrid_rerank"

    def retrieve(self, _q: str, k: int = 8, **_kwargs):  # noqa: ANN001
        return []


def _hit(doc_id: str, title: str, text: str, score: float = 1.0) -> RetrievalHit:
    chunk = ScoredChunk(
        chunk_id=f"{doc_id}:0",
        doc_id=doc_id,
        version=1,
        text=text,
        score=score,
        chunk_index=0,
        title=title,
    )
    return RetrievalHit(chunk=chunk, fused_score=score)


def test_colony_degraded_preview_drops_unrelated_titles() -> None:
    engine = InvestigationEngine(
        retriever=_DummyRetriever(),  # type: ignore[arg-type]
        store=_DummyStore(),  # type: ignore[arg-type]
        llm=None,
        settings=Settings(tau_relative=0.35),
    )
    tools = ToolExecutor(
        retriever=_DummyRetriever(),  # type: ignore[arg-type]
        store=_DummyStore(),  # type: ignore[arg-type]
        top_k=5,
        tau_retrieval=0.0,
        tau_relative=0.35,
        injection_downweight=0.05,
    )
    tools.state.retrieved = [
        _hit(
            "airport",
            "Roanoke–Blacksburg Regional Airport",
            "Woodrum Field is northwest of Roanoke, Virginia.",
        ),
        _hit(
            "alien",
            "Alien Investigations",
            "A television series about paranormal investigations.",
        ),
        _hit(
            "tavern",
            "White Horse Tavern, Cambridge",
            "A historic pub with no colony content.",
        ),
    ]
    result = engine._degraded(
        "Which evidence connects the investigation of the Roanoke colony "
        "disappearance to the key individuals involved?",
        plan=None,
        tools=tools,
        trace=TraceRecorder(),
        usage=UsageStats(),
        reason="LLM provider unavailable after retries/fallback.",
    )
    titles = {(p.get("title") or "").lower() for p in result.evidence_preview}
    assert "alien investigations" not in titles
    assert "white horse tavern, cambridge" not in titles
    # Airport shares "Roanoke" weakly; multi-token colony phrase should keep it weak.
    assert not any("airport" in t for t in titles)
