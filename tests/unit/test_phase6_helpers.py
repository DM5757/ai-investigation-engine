"""Unit tests for Phase 6 pure helpers (no cloud)."""

from __future__ import annotations

from scripts._phase6_common import estimate_from_pilot
from scripts.build_corpus import (
    _paragraph_from_context_item,
    _stable_title_key,
    extract_unique_paragraphs,
)
from scripts.crc32_collision_analysis import analyze_terms


def test_stable_title_key() -> None:
    assert _stable_title_key("  Foo Bar  ") == "hotpotqa:Foo Bar"


def test_paragraph_from_context_item() -> None:
    assert _paragraph_from_context_item(["Title", ["A.", "B."]]) == ("Title", "A. B.")
    assert _paragraph_from_context_item(["X", "plain"]) == ("X", "plain")
    assert _paragraph_from_context_item(["", ["no"]]) is None


def test_extract_unique_paragraphs_seeded() -> None:
    examples = [
        {
            "context": [
                ["Alpha", ["Sentence one."]],
                ["Beta", ["Sentence two."]],
            ]
        },
        {
            "context": {
                "title": ["Alpha", "Gamma"],
                "sentences": [["Dup alpha."], ["Sentence three."]],
            }
        },
    ]
    a = extract_unique_paragraphs(examples, seed=1, limit=10)
    b = extract_unique_paragraphs(examples, seed=1, limit=10)
    assert [r["id"] for r in a] == [r["id"] for r in b]
    assert len({r["id"] for r in a}) == len(a)
    assert all(r["id"].startswith("hotpotqa:") for r in a)
    # Alpha deduped
    assert sum(1 for r in a if r["title"] == "Alpha") == 1


def test_estimate_go_when_small() -> None:
    est = estimate_from_pilot(
        pilot_docs=500,
        pilot_neon_bytes=5_000_000,
        pilot_qdrant_points=600,
        pilot_estimated_qdrant_disk=8_000_000,
        pilot_wall_s=50.0,
        target_docs=55_000,
    )
    assert est["full_ingest_go"] is True
    assert est["neon_bytes_estimate"] == 5_000_000 * 55_000 // 500


def test_estimate_nogo_neon() -> None:
    est = estimate_from_pilot(
        pilot_docs=100,
        pilot_neon_bytes=50_000_000,
        pilot_qdrant_points=120,
        pilot_estimated_qdrant_disk=1_000_000,
        pilot_wall_s=10.0,
        target_docs=55_000,
    )
    # 50MB * 550 = 27.5 GB >> neon safe
    assert est["full_ingest_go"] is False
    assert est["proposed_max_safe_docs"] < 55_000


def test_crc32_analysis_no_collision_trivial() -> None:
    out = analyze_terms({"payment", "service", "gateway"})
    assert out["unique_terms"] == 3
    assert out["collision_id_count"] == 0
    assert out["assessment"] == "negligible"
