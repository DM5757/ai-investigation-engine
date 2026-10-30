"""Heuristic claim extraction must capture anaphoric follow-on facts."""

from __future__ import annotations

from app.investigation.extractor import heuristic_claims_from_chunk


def test_anaphora_pulls_location_after_entity_intro() -> None:
    text = (
        "California State University, Dominguez Hills (also known as CSUDH) "
        "is a public university within the 23-school California State "
        "University (CSU) system. It is located in the city of Carson, "
        "California in the South Bay region of Los Angeles County and was "
        "founded in 1960."
    )
    claims = heuristic_claims_from_chunk(
        chunk_id="c1",
        doc_id="d1",
        text=text,
        subject_hint="California State University, Dominguez Hills",
        claim_prefix="h",
        source_title="California State University, Dominguez Hills",
    )
    joined = " ".join(c.quote for c in claims).lower()
    assert "carson" in joined
    assert any("located" in c.quote.lower() for c in claims)


def test_anaphora_keeps_nickname_bridge_mention() -> None:
    text = (
        "Mary Robinson (née Darby) was an English actress and poet. "
        'During her lifetime she was known as "the English Sappho". '
        'She earned her nickname "Perdita" for her role as Perdita '
        '(heroine of Shakespeare\'s "The Winter\'s Tale") in 1779.'
    )
    claims = heuristic_claims_from_chunk(
        chunk_id="c3",
        doc_id="d3",
        text=text,
        subject_hint="Mary Robinson",
        claim_prefix="h",
        source_title="Mary Robinson (poet)",
    )
    joined = " ".join(c.quote for c in claims).lower()
    assert "perdita" in joined


def test_ohio_location_sentence_kept() -> None:
    text = (
        "The Ohio State University, commonly referred to as Ohio State or OSU, "
        "is a large, primarily residential, public university in Columbus, Ohio. "
        "Founded in 1870 as a land-grant university."
    )
    claims = heuristic_claims_from_chunk(
        chunk_id="c2",
        doc_id="d2",
        text=text,
        subject_hint="Ohio State University",
        claim_prefix="h",
        source_title="Ohio State University",
    )
    joined = " ".join(c.quote for c in claims).lower()
    assert "columbus" in joined
