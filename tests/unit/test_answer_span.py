"""Short answer-span extraction for Hotpot-style evaluation."""

from __future__ import annotations

from app.investigation.answer_span import (
    extract_span_from_claims,
    needs_llm_synthesis,
    question_answer_kind,
)
from app.schemas.evidence import Claim


def _c(cid: str, title: str, quote: str) -> Claim:
    return Claim(
        claim_id=cid,
        subject=title,
        attribute="statement",
        value=quote[:120],
        quote=quote,
        chunk_id=cid,
        doc_id=cid,
        verified=True,
        source_title=title,
    )


def test_date_span_from_premiere() -> None:
    q = (
        "Michael Lent is best known as the co-writer of the memoirs of "
        "Hugh Rowland, a star on a reality television series that "
        "premiered on what date?"
    )
    claims = [
        _c(
            "1",
            "Ice Road Truckers",
            "Ice Road Truckers is a reality television series that premiered "
            "on History, on June 17, 2007.",
        )
    ]
    hit = extract_span_from_claims(q, claims)
    assert hit is not None
    span, support, conf = hit
    assert "2007" in span
    assert "June" in span
    assert conf >= 0.7
    assert support


def test_comparison_span_is_winning_entity() -> None:
    q = (
        "Is Ohio State University or California State University, "
        "Dominguez Hills further west?"
    )
    claims = [
        _c(
            "1",
            "Ohio State University",
            "public university in Columbus, Ohio.",
        ),
        _c(
            "2",
            "California State University, Dominguez Hills",
            "located in the city of Carson, California.",
        ),
    ]
    hit = extract_span_from_claims(q, claims)
    assert hit is not None
    span, _support, conf = hit
    assert "Dominguez" in span
    assert conf >= 0.7
    assert question_answer_kind(q) == "comparison"


def test_production_company_span() -> None:
    q = (
        "Which company owned by a Pakistani media mogul produced the "
        "Pakistani romantic drama film Dobara Phir Se?"
    )
    claims = [
        _c(
            "1",
            "Dobara Phir Se",
            "Dobara Phir Se is a 2016 Pakistani romantic drama film directed "
            "by Mehreen Jabbar and a production of ARY Films.",
        )
    ]
    hit = extract_span_from_claims(q, claims)
    assert hit is not None
    assert "ARY Films" in hit[0]


def test_high_confidence_span_skips_llm() -> None:
    assert not needs_llm_synthesis(
        "When did it premiere?",
        [],
        status="answered",
        span_confidence=0.92,
    )
    assert needs_llm_synthesis(
        "Explain the relationship between A and B across documents.",
        [],
        status="answered",
        span_confidence=0.4,
    )
    # Weak title guesses must not lock into deterministic mode.
    assert needs_llm_synthesis(
        "Which star was born April 20, 1949?",
        [],
        status="answered",
        span_confidence=0.55,
    )


def test_jwt_misconfig_span() -> None:
    hit = extract_span_from_claims(
        "What misconfiguration on AuthGateway was reported in the March incident?",
        [
            _c(
                "1",
                "Incident Report — Payment Outage March",
                "A misconfigured JWT TTL on AuthGateway caused cascading retries "
                "into PaymentService.",
            )
        ],
    )
    assert hit is not None
    assert "JWT" in hit[0]
    assert "TTL" in hit[0]


def test_abbrev_and_born_spans() -> None:
    abbr = extract_span_from_claims(
        "What is the abbreviation for the movie which starred Saif Ali Khan in 2003?",
        [
            _c(
                "1",
                "Kal Ho Naa Ho",
                "Kal Ho Naa Ho (KHNH) is a 2003 Indian romance film starring Saif Ali Khan.",
            )
        ],
    )
    assert abbr is not None
    assert abbr[0] == "KHNH"

    born = extract_span_from_claims(
        "Which star in the movie Hush was born April 20, 1949?",
        [
            _c(
                "1",
                "Hush (1998 film)",
                "Jessica Lange (born April 20, 1949) starred in Hush.",
            )
        ],
    )
    assert born is not None
    assert "Jessica Lange" in born[0]
