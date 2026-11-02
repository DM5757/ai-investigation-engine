"""Deterministic fast-path helpers for skipping unnecessary LLM rounds."""

from __future__ import annotations

from app.investigation.fast_path import (
    comparison_direction,
    seed_retrieval_sufficient,
    state_westness,
)
from app.investigation.synthesizer import deterministic_synthesize
from app.schemas.evidence import Claim


class _Chunk:
    def __init__(self, title: str) -> None:
        self.title = title
        self.text = f"{title} text"
        self.chunk_id = title
        self.doc_id = title


class _Hit:
    def __init__(self, title: str) -> None:
        self.chunk = _Chunk(title)


class _State:
    def __init__(self, titles: list[str]) -> None:
        self.retrieved = [_Hit(t) for t in titles]


class _Tools:
    def __init__(self, titles: list[str]) -> None:
        self.state = _State(titles)


def test_seed_sufficient_for_comparison_both_titles() -> None:
    q = (
        "Is Ohio State University or California State University, "
        "Dominguez Hills further west?"
    )
    tools = _Tools(
        [
            "Ohio State University",
            "California State University, Dominguez Hills",
        ]
    )
    assert seed_retrieval_sufficient(q, tools)  # type: ignore[arg-type]


def test_seed_insufficient_when_peer_missing() -> None:
    q = (
        "Is Ohio State University or California State University, "
        "Dominguez Hills further west?"
    )
    tools = _Tools(["Ohio State University"])
    assert not seed_retrieval_sufficient(q, tools)  # type: ignore[arg-type]


def test_deterministic_west_comparison_uses_state_rank() -> None:
    q = (
        "Is Ohio State University or California State University, "
        "Dominguez Hills further west?"
    )
    claims = [
        Claim(
            claim_id="1",
            subject="Ohio State University",
            attribute="location",
            value="Columbus, Ohio",
            quote="public university in Columbus, Ohio.",
            chunk_id="c1",
            doc_id="d1",
            verified=True,
            source_title="Ohio State University",
            source_label="S1",
        ),
        Claim(
            claim_id="2",
            subject="California State University, Dominguez Hills",
            attribute="location",
            value="Carson, California",
            quote="located in the city of Carson, California.",
            chunk_id="c2",
            doc_id="d2",
            verified=True,
            source_title="California State University, Dominguez Hills",
            source_label="S2",
        ),
    ]
    text, cites = deterministic_synthesize(
        question=q,
        status="answered",
        claims=claims,
        conflicts=[],
        abstention_reason=None,
    )
    assert text is not None
    assert "further west" in text.lower()
    assert "dominguez" in text.lower()
    assert comparison_direction(q) == "west"
    assert state_westness("Carson, California") is not None
    assert state_westness("Columbus, Ohio") is not None
    assert len(cites) >= 1


def test_deterministic_factual_uses_quote() -> None:
    text, cites = deterministic_synthesize(
        question="Where is the airport?",
        status="answered",
        claims=[
            Claim(
                claim_id="1",
                subject="Airport",
                attribute="location",
                value="Roanoke",
                quote="Woodrum Field is near Roanoke, Virginia.",
                chunk_id="c1",
                doc_id="d1",
                verified=True,
                source_title="Roanoke–Blacksburg Regional Airport",
                source_label="S1",
            )
        ],
        conflicts=[],
        abstention_reason=None,
    )
    assert text is not None
    assert "Woodrum Field" in text
    assert "[S1]" in text
    assert len(cites) == 1
