"""Quote verification accept/reject."""

from __future__ import annotations

from app.investigation.extractor import quote_appears_in_chunk, verify_claim_quote
from app.schemas.evidence import Claim


def test_quote_accepts_normalized_match() -> None:
    chunk = "The  Auth-Gateway  deploy caused PaymentService  disruptions."
    quote = "auth-gateway deploy caused paymentservice disruptions"
    assert quote_appears_in_chunk(quote, chunk)


def test_quote_rejects_fabricated() -> None:
    chunk = "InventoryService was unaffected in March."
    quote = "PaymentService was deleted permanently"
    assert not quote_appears_in_chunk(quote, chunk)


def test_verify_claim_quote_sets_flag() -> None:
    claim = Claim(
        claim_id="c1",
        subject="PaymentService",
        attribute="status",
        value="disrupted",
        quote="PaymentService disruptions",
        chunk_id="x",
        doc_id="d",
    )
    ok = verify_claim_quote(claim, "There were PaymentService disruptions after deploy.")
    bad = verify_claim_quote(claim, "Nothing about payments here.")
    assert ok.verified is True
    assert bad.verified is False
