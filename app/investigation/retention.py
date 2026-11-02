"""Evaluation-only evidence retention / provenance tracking.

Records document IDs and titles at each investigation stage so eval can
measure where gold support is lost. Never receives gold labels — callers
compute coverage separately.

Disabled by default; enable via Settings.eval_record_retention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.evidence import Citation, Claim


@dataclass
class StageSnapshot:
    stage: str
    doc_ids: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    n_items: int = 0
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "doc_ids": list(self.doc_ids),
            "titles": list(self.titles),
            "n_docs": len(self.doc_ids),
            "n_items": self.n_items,
            "note": self.note,
        }


class RetentionTracker:
    """Append-only stage snapshots (doc ids/titles only — no passage text)."""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self.stages: list[StageSnapshot] = []

    def record(
        self,
        stage: str,
        *,
        doc_ids: list[str] | None = None,
        titles: list[str] | None = None,
        n_items: int = 0,
        note: str = "",
    ) -> None:
        if not self.enabled:
            return
        ids = list(dict.fromkeys(d for d in (doc_ids or []) if d))
        tits = list(dict.fromkeys(t for t in (titles or []) if t))
        self.stages.append(
            StageSnapshot(
                stage=stage,
                doc_ids=ids,
                titles=tits,
                n_items=n_items,
                note=note[:200],
            )
        )

    def record_hits(self, stage: str, hits: list[Any], *, note: str = "") -> None:
        if not self.enabled:
            return
        doc_ids: list[str] = []
        titles: list[str] = []
        for hit in hits:
            chunk = getattr(hit, "chunk", None)
            if chunk is None and isinstance(hit, dict):
                doc_ids.append(str(hit.get("doc_id") or ""))
                titles.append(str(hit.get("title") or ""))
                continue
            if chunk is None:
                continue
            doc_ids.append(str(getattr(chunk, "doc_id", "") or ""))
            titles.append(str(getattr(chunk, "title", "") or ""))
        self.record(stage, doc_ids=doc_ids, titles=titles, n_items=len(hits), note=note)

    def record_claims(self, stage: str, claims: list[Claim], *, note: str = "") -> None:
        if not self.enabled:
            return
        self.record(
            stage,
            doc_ids=[c.doc_id for c in claims],
            titles=[c.source_title or "" for c in claims],
            n_items=len(claims),
            note=note,
        )

    def record_citations(
        self, stage: str, citations: list[Citation], *, note: str = ""
    ) -> None:
        if not self.enabled:
            return
        self.record(
            stage,
            doc_ids=[c.doc_id for c in citations],
            titles=[],
            n_items=len(citations),
            note=note,
        )

    def as_dict(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        return {
            "stages": [s.as_dict() for s in self.stages],
        }

