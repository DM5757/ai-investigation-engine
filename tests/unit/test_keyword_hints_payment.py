"""Regression: multi-doc payment questions must keep domain hint tokens."""

from __future__ import annotations

from pathlib import Path

from app.investigation.engine import _keyword_hints
from app.investigation.extractor import heuristic_claims_from_chunk
from app.investigation.question_focus import filter_claims_for_question
from app.investigation.sufficiency import assess_sufficiency

QUESTION = (
    "Which system changes caused disruptions in payment processing in March, "
    "which services were affected, and which documents support this?"
)


def test_payment_hints_prefer_corpus_terms() -> None:
    text = (Path("data/synthetic/incident_march.md")).read_text(encoding="utf-8")
    hints = _keyword_hints(QUESTION, prefer_in_text=text)
    low = {h.lower() for h in hints}
    assert "payment" in low or "march" in low or "paymentservice" in low
    # Length alone must not crowd out domain terms with absent long tokens
    assert "disruptions" not in low or "payment" in low


def test_payment_incident_yields_verified_claims() -> None:
    text = (Path("data/synthetic/incident_march.md")).read_text(encoding="utf-8")
    hints = _keyword_hints(QUESTION, prefer_in_text=text)
    claims = []
    for hint in hints:
        claims.extend(
            heuristic_claims_from_chunk(
                chunk_id="c1",
                doc_id="d1",
                text=text,
                subject_hint=hint,
                claim_prefix=f"h-{hint}",
            )
        )
    verified = [c for c in claims if c.verified]
    assert verified
    supporting, _weak, focus = filter_claims_for_question(verified, QUESTION)
    assert supporting
    status, _ = assess_sufficiency(
        verified_claims=supporting, conflicts=[], question=QUESTION, focus=focus
    )
    assert status in ("answered", "partial", "conflicting")
