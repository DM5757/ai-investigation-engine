"""Multi-entity extraction and title fidelity (no hardcoding of gold answers)."""

from __future__ import annotations

from app.investigation.entities import (
    entity_title_fidelity,
    extract_focus_entities,
)
from app.investigation.question_focus import extract_question_focus
from app.investigation.sufficiency import assess_sufficiency
from app.schemas.evidence import Claim


def test_extracts_or_comparison_entities() -> None:
    q = (
        "Is Ohio State University or California State University, "
        "Dominguez Hills further west?"
    )
    ents = extract_focus_entities(q)
    assert any(e == "Ohio State University" for e in ents)
    assert any("Dominguez Hills" in e for e in ents)
    assert not any(e.lower().startswith("is ") for e in ents)


def test_title_fidelity_prefers_exact_over_campus_extension() -> None:
    entity = "Ohio State University"
    exact = entity_title_fidelity(entity, "Ohio State University")
    campus = entity_title_fidelity(entity, "Ohio State University, Mansfield Campus")
    assert exact > campus
    assert campus < 0.4


def test_focus_phrases_include_comparison_entities() -> None:
    q = (
        "Is Ohio State University or California State University, "
        "Dominguez Hills further west?"
    )
    focus = extract_question_focus(q)
    joined = " | ".join(focus.phrases).lower()
    assert "ohio state university" in joined
    assert "dominguez" in joined
    assert "hills further" not in joined


def test_bridge_queries_surface_unretrieved_titles() -> None:
    from app.investigation.entities import bridge_entity_queries

    bridges = bridge_entity_queries(
        question="What country was the character Mary Robinson was nicknamed for from?",
        retrieved_titles=["Mary Robinson (poet)"],
        retrieved_texts=[
            "Mary Robinson was nicknamed Perdita after the heroine of "
            "The Winter's Tale by William Shakespeare."
        ],
        known_entities=["Mary Robinson"],
        max_bridges=3,
    )
    joined = " | ".join(bridges).lower()
    assert "perdita" in joined or "winter" in joined


def test_multi_entity_sufficiency_requires_both_sides() -> None:
    q = (
        "Is Ohio State University or California State University, "
        "Dominguez Hills further west?"
    )
    one_side = [
        Claim(
            claim_id="1",
            subject="Ohio State University",
            attribute="location",
            value="Columbus, Ohio",
            quote="Ohio State University is in Columbus, Ohio.",
            chunk_id="c1",
            doc_id="d1",
            verified=True,
            source_title="Ohio State University",
        )
    ]
    status, reason = assess_sufficiency(
        verified_claims=one_side, conflicts=[], question=q, min_support=0.55
    )
    assert status == "insufficient"
    assert reason and "two entities" in reason.lower()

    both = one_side + [
        Claim(
            claim_id="2",
            subject="California State University, Dominguez Hills",
            attribute="location",
            value="Carson, California",
            quote="California State University, Dominguez Hills is in Carson, California.",
            chunk_id="c2",
            doc_id="d2",
            verified=True,
            source_title="California State University, Dominguez Hills",
        )
    ]
    status2, _ = assess_sufficiency(
        verified_claims=both, conflicts=[], question=q, min_support=0.55
    )
    assert status2 == "answered"
