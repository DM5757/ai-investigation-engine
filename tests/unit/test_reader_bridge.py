"""Iterative bridge retrieval keeps a better verified reader outcome."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.config import Settings
from app.investigation.engine import InvestigationEngine
from app.investigation.reader import ReaderOutput, ReaderPassage
from app.llm.scripted import ScriptedLLM
from app.schemas.evidence import Citation, UsageStats


def test_finalize_with_reader_runs_bridge_on_partial(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        EXPERIMENTAL_PASSAGE_READER="true",
        READER_MULTI_HOP_POLICY="soft",
        READER_MAX_BRIDGE_ROUNDS="1",
    )
    engine = InvestigationEngine(
        retriever=MagicMock(),
        store=MagicMock(),
        llm=ScriptedLLM(responses=[]),
        settings=settings,
    )

    calls: list[str] = []

    def fake_read(**kwargs: Any) -> ReaderOutput:
        calls.append("read")
        n = len(calls)
        if n == 1:
            return ReaderOutput(
                answer="June 17, 2007",
                answerable=False,
                status="partial",
                next_query="Michael Lent memoirs",
                answer_supported=True,
                evidence_chain_ok=False,
                verify_ok=True,
                citations=[
                    Citation(label="S1", chunk_id="c1", doc_id="d1", quote="premiered")
                ],
                usage=UsageStats(calls=1, total_tokens=10),
                missing_info="Need second hop",
            )
        return ReaderOutput(
            answer="June 17, 2007",
            answerable=True,
            status="answered",
            next_query=None,
            answer_supported=True,
            evidence_chain_ok=True,
            verify_ok=True,
            citations=[
                Citation(label="S1", chunk_id="c1", doc_id="d1", quote="premiered"),
                Citation(label="S2", chunk_id="c2", doc_id="d2", quote="Hugh"),
            ],
            usage=UsageStats(calls=1, total_tokens=12),
        )

    monkeypatch.setattr(
        "app.investigation.engine.read_passages", fake_read
    )
    monkeypatch.setattr(
        "app.investigation.engine.passages_from_retrieval_hits",
        lambda hits, max_n=10: [
            ReaderPassage(label="S1", title="A", text="premiered on June 17, 2007")
        ],
    )

    tools = MagicMock()
    tools.state.retrieved = []
    tools.state.findings = []
    tools.execute = MagicMock(return_value={"results": []})

    from app.investigation.trace import TraceRecorder

    trace = TraceRecorder()
    resp = engine._finalize_with_reader(
        "When did it premiere?",
        plan=None,
        tools=tools,
        trace=trace,
        usage_total=UsageStats(),
    )
    assert tools.execute.called
    assert len(calls) == 2
    assert resp.status == "answered"
    assert len(resp.citations) == 2
