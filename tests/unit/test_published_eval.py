"""Published evaluation artifact used by /api/eval/runs."""

from __future__ import annotations

import json
from pathlib import Path

from app.api.routes_stats import _load_published_eval


def test_published_eval_file_exists_and_matches_loader() -> None:
    path = Path(__file__).resolve().parents[2] / "app" / "data" / "published_eval.json"
    assert path.is_file()
    disk = json.loads(path.read_text(encoding="utf-8"))
    loaded = _load_published_eval()
    assert loaded["runs"]
    assert loaded["runs"][0]["run_id"] == disk["runs"][0]["run_id"]
    assert loaded["corpus_at_eval"]["active_documents"] == 55081


def test_published_eval_does_not_claim_smoke_as_accuracy() -> None:
    data = _load_published_eval()
    blob = json.dumps(data).lower()
    assert "not overall accuracy" in blob or "not" in (data.get("note") or "").lower()
    assert data["limitations"]
