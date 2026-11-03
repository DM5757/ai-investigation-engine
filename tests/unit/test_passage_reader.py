"""Unit tests for experimental passage reader verification (Phase B/C/C.1)."""

from __future__ import annotations

import json

from app.errors import LLMUnavailable
from app.investigation.reader import (
    ReaderPassage,
    read_passages,
    verify_reader_payload,
)
from app.investigation.verify import MultiHopPolicy
from app.llm.scripted import ScriptedLLM, ScriptedResponse
from app.schemas.evidence import UsageStats


def _passages() -> list[ReaderPassage]:
    return [
        ReaderPassage(
            label="S1",
            title="Ice Road Truckers",
            text=(
                "Ice Road Truckers is a reality television series that "
                "premiered on June 17, 2007."
            ),
            doc_id="d1",
            chunk_id="c1",
        ),
        ReaderPassage(
            label="S2",
            title="Michael Lent",
            text="Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland.",
            doc_id="d2",
            chunk_id="c2",
        ),
    ]


def test_verify_accepts_exact_quote_and_supported_answer() -> None:
    data = {
        "answer": "June 17, 2007",
        "answerable": True,
        "supporting": [
            {"label": "S1", "quote": "premiered on June 17, 2007", "role": "support"}
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(data, _passages(), require_multi_hop=False)
    assert out.answerable
    assert out.answer_supported
    assert out.verify_ok
    assert out.status == "answered"


def test_coverage_threshold_065_accepts_borderline() -> None:
    # 2 of 3 content tokens in quotes → ~0.67; fails at 0.85, passes at 0.65.
    data = {
        "answer": "Hugh Leon Rowland",
        "answerable": True,
        "supporting": [
            {"label": "S2", "quote": "memoirs of Hugh Rowland", "role": "support"}
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out_strict = verify_reader_payload(
        data, _passages(), require_multi_hop=False, coverage_threshold=0.85
    )
    out_cal = verify_reader_payload(
        data, _passages(), require_multi_hop=False, coverage_threshold=0.65
    )
    assert out_strict.status == "insufficient"
    assert out_cal.status == "answered"
    assert out_cal.coverage >= 0.66


def test_strict_incomplete_chain_abstains() -> None:
    data = {
        "answer": "June 17, 2007",
        "answerable": True,
        "supporting": [
            {"label": "S1", "quote": "premiered on June 17, 2007", "role": "hop1"}
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(
        data,
        _passages(),
        require_multi_hop=True,
        min_hops=2,
        policy=MultiHopPolicy.STRICT,
    )
    assert out.status == "insufficient"
    assert out.answer is None
    assert any(r.startswith("incomplete_evidence_chain") for r in out.unsupported_reasons)


def test_soft_incomplete_chain_returns_partial() -> None:
    data = {
        "answer": "June 17, 2007",
        "answerable": True,
        "supporting": [
            {"label": "S1", "quote": "premiered on June 17, 2007", "role": "hop1"}
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(
        data,
        _passages(),
        require_multi_hop=True,
        min_hops=2,
        policy=MultiHopPolicy.SOFT,
    )
    assert out.status == "partial"
    assert out.answer == "June 17, 2007"
    assert out.answer_supported
    assert not out.evidence_chain_ok
    assert out.next_query


def test_soft_never_full_answered_without_chain() -> None:
    data = {
        "answer": "June 17, 2007",
        "answerable": True,
        "supporting": [
            {"label": "S1", "quote": "premiered on June 17, 2007", "role": "hop1"}
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(
        data, _passages(), require_multi_hop=True, policy="soft"
    )
    assert out.status != "answered"
    assert not out.answerable


def test_verify_rejects_invented_label_and_bad_quote() -> None:
    data = {
        "answer": "June 17, 2007",
        "answerable": True,
        "supporting": [
            {"label": "S9", "quote": "premiered on June 17, 2007"},
            {"label": "S1", "quote": "this quote is not in the passage"},
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(data, _passages(), require_multi_hop=False)
    assert not out.answerable
    assert "invalid_label:S9" in out.unsupported_reasons


def test_verify_rejects_answer_not_entailed_by_quotes() -> None:
    data = {
        "answer": "December 25, 1999",
        "answerable": True,
        "supporting": [{"label": "S1", "quote": "reality television series"}],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(data, _passages(), require_multi_hop=False)
    assert out.status == "insufficient"
    assert out.answer is None


def test_multi_hop_accepts_complete_chain() -> None:
    data = {
        "answer": "Hugh Rowland",
        "answerable": True,
        "supporting": [
            {
                "label": "S1",
                "quote": "Ice Road Truckers is a reality television series",
                "role": "hop1",
            },
            {
                "label": "S2",
                "quote": "co-writer of the memoirs of Hugh Rowland",
                "role": "hop2",
            },
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(data, _passages(), require_multi_hop=True, min_hops=2)
    assert out.status == "answered"
    assert out.evidence_chain_ok


def test_model_reported_contradiction() -> None:
    passages = [
        ReaderPassage(
            label="S1",
            title="Brief A",
            text="Project Nebula launched on 12 January 2021 after board approval.",
        ),
        ReaderPassage(
            label="S2",
            title="Brief B",
            text="Project Nebula launched on 12 March 2021 following a delayed review.",
        ),
    ]
    data = {
        "answer": None,
        "answerable": False,
        "supporting": [
            {"label": "S1", "quote": "launched on 12 January 2021"},
            {"label": "S2", "quote": "launched on 12 March 2021"},
        ],
        "missing_info": "Conflicting launch dates.",
        "next_query": None,
        "conflict_kind": "contradiction",
    }
    out = verify_reader_payload(data, passages, require_multi_hop=False)
    assert out.status == "conflicting"


def test_read_passages_with_scripted_llm() -> None:
    payload = {
        "answer": "June 17, 2007",
        "answerable": True,
        "supporting": [
            {"label": "S1", "quote": "premiered on June 17, 2007", "role": "support"}
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    llm = ScriptedLLM(
        responses=[
            ScriptedResponse(
                content=json.dumps(payload),
                usage=UsageStats(calls=1, total_tokens=20),
            )
        ]
    )
    out = read_passages(
        question="When did the series premiere?",
        passages=_passages(),
        llm=llm,
        require_multi_hop=False,
    )
    assert out.status == "answered"
    assert out.raw_model.get("answer") == "June 17, 2007"


def test_provider_unavailable_surfaces() -> None:
    llm = ScriptedLLM(responses=[LLMUnavailable("quota exhausted")])
    try:
        read_passages(
            question="When did the series premiere?",
            passages=_passages(),
            llm=llm,
        )
        raise AssertionError("expected LLMUnavailable")
    except LLMUnavailable as exc:
        assert "quota" in str(exc).lower()


def test_empty_passages_insufficient() -> None:
    out = read_passages(
        question="Anything?",
        passages=[],
        llm=ScriptedLLM(responses=[]),
    )
    assert out.status == "insufficient"


def test_experimental_policy_default_soft_in_settings() -> None:
    from app.config import Settings

    s = Settings(DATABASE_URL="sqlite+pysqlite:///:memory:")
    assert s.experimental_passage_reader is False
    assert s.reader_multi_hop_policy == "soft"
    assert abs(s.reader_coverage_threshold - 0.65) < 1e-9
    assert s.reader_max_bridge_rounds == 1
    assert s.reader_preferred_mode == "hybrid_rrf"


def test_paraphrase_answer_supported_via_cited_passage() -> None:
    """Paraphrased short answer accepted when present in the cited passage."""
    data = {
        "answer": "Hugh Rowland",
        "answerable": True,
        "supporting": [
            {
                "label": "S2",
                "quote": "Michael Lent is best known as the co-writer",
                "role": "support",
            }
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(data, _passages(), require_multi_hop=False)
    assert out.status == "answered"
    assert out.answer_supported
    assert out.coverage >= 0.65


def test_passage_support_requires_valid_quote() -> None:
    data = {
        "answer": "Hugh Rowland",
        "answerable": True,
        "supporting": [
            {"label": "S2", "quote": "this quote is not in the passage", "role": "support"}
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(data, _passages(), require_multi_hop=False)
    assert out.status == "insufficient"
    assert not out.answer_supported


def test_middle_initial_variant_coverage() -> None:
    data = {
        "answer": "Hugh M Rowland",
        "answerable": True,
        "supporting": [
            {"label": "S2", "quote": "memoirs of Hugh Rowland", "role": "support"}
        ],
        "missing_info": None,
        "next_query": None,
        "conflict_kind": "none",
    }
    out = verify_reader_payload(
        data, _passages(), require_multi_hop=False, coverage_threshold=0.65
    )
    assert out.status == "answered"
    assert out.answer_supported


def test_negative_control_builders() -> None:
    from eval.negative_controls import CONTROLS

    q = {
        "id": "t1",
        "question": "Who wrote what?",
        "gold_paragraphs": [
            {"title": "A", "text": "Alice wrote the red book in 1991."},
            {"title": "B", "text": "The red book won a prize in Spain."},
        ],
    }
    assert CONTROLS["remove_gold"](q) == []
    assert len(CONTROLS["missing_one_hop"](q)) == 1
