"""Phase C rigorous negative-control passage builders (development only)."""

from __future__ import annotations

import hashlib
import random
from typing import Any

from app.investigation.reader import ReaderPassage, passages_from_gold_paragraphs

# Fixed distractor bank — unrelated to Hotpot gold, comparable length.
_DISTRACTORS: list[dict[str, str]] = [
    {
        "title": "Alpine Trail Maintenance Handbook",
        "text": (
            "Section 4 recommends clearing drainage dips before the spring thaw. "
            "Crews logged 42 kilometers of tread repair in 2019 across the north ridge."
        ),
    },
    {
        "title": "Municipal Compost Ordinance 14-B",
        "text": (
            "Residential food scraps must be separated weekly. The city estimates "
            "a 12 percent diversion rate after the pilot in Ward Three."
        ),
    },
    {
        "title": "Ceramic Glaze Safety Notes",
        "text": (
            "Lead-bearing frits require kiln ventilation above 900 degrees Celsius. "
            "Studio managers must post SDS sheets near the mixing bench."
        ),
    },
    {
        "title": "Ferry Timetable Addendum",
        "text": (
            "The evening sailing departs at 18:40 local time except on public holidays. "
            "Bicycle spaces are limited to sixteen per crossing."
        ),
    },
    {
        "title": "Library Binding Standards",
        "text": (
            "Spine lettering should use 14-point sans-serif type. Acid-free endpapers "
            "are mandatory for archival loans longer than thirty days."
        ),
    },
    {
        "title": "Aquaculture Feed Trial Summary",
        "text": (
            "Trout fed the algae blend gained 8.3 percent more mass over twelve weeks. "
            "Mortality remained under two percent in both tanks."
        ),
    },
]


def _seed_for(question_id: str, control: str) -> int:
    blob = f"{question_id}|{control}".encode()
    return int(hashlib.sha256(blob).hexdigest()[:8], 16)


def gold_passages(question: dict[str, Any]) -> list[ReaderPassage]:
    paras = list(question.get("query_only_passages") or question.get("gold_paragraphs") or [])
    return passages_from_gold_paragraphs(paras)


def control_remove_gold(question: dict[str, Any]) -> list[ReaderPassage]:
    """A: remove all gold supporting passages (empty context)."""
    return []


def control_distractors(
    question: dict[str, Any], *, n: int = 2
) -> list[ReaderPassage]:
    """B: replace gold with unrelated distractors of similar length."""
    rng = random.Random(_seed_for(str(question.get("id")), "distractors"))
    picks = rng.sample(_DISTRACTORS, k=min(n, len(_DISTRACTORS)))
    # Match approximate total length of gold when available.
    gold = gold_passages(question)
    target = sum(len(p.text) for p in gold) if gold else 400
    out: list[ReaderPassage] = []
    for i, d in enumerate(picks, start=1):
        text = d["text"]
        while len(text) < target // max(1, len(picks)) and len(text) < 2000:
            text = text + " " + d["text"]
        out.append(
            ReaderPassage(label=f"S{i}", title=d["title"], text=text[: max(200, target // n)])
        )
    return out


def control_swap_labels(question: dict[str, Any]) -> list[ReaderPassage]:
    """C: keep gold texts but assign non-matching synthetic titles/labels provenance.

    Titles are replaced with distractor titles while texts stay gold — provenance
    checking must still bind quotes to the supplied label's text, not the title.
    """
    gold = gold_passages(question)
    if len(gold) < 2:
        return gold
    rng = random.Random(_seed_for(str(question.get("id")), "swap_labels"))
    titles = [d["title"] for d in rng.sample(_DISTRACTORS, k=len(gold))]
    out: list[ReaderPassage] = []
    for i, (p, title) in enumerate(zip(gold, titles, strict=True), start=1):
        out.append(
            ReaderPassage(
                label=f"S{i}",
                title=title,
                text=p.text,
                doc_id=p.doc_id,
                chunk_id=p.chunk_id,
            )
        )
    return out


def control_counterfactual(question: dict[str, Any]) -> list[ReaderPassage]:
    """D: synthetic counterfactual facts that pretrained knowledge cannot recover."""
    rng = random.Random(_seed_for(str(question.get("id")), "counterfactual"))
    city = rng.choice(["Zenthara", "Quorvail", "Meldune", "Braskel"])
    year = rng.choice([2117, 2142, 2099, 2201])
    alloy = rng.choice(["aetherium-7", "silvex-blue", "norbium-X"])
    return [
        ReaderPassage(
            label="S1",
            title=f"{city} Founding Charter",
            text=(
                f"The free city of {city} was chartered in {year} after the "
                f"Coastal Compact. Its municipal seal depicts a {alloy} compass."
            ),
        ),
        ReaderPassage(
            label="S2",
            title=f"{city} Materials Registry",
            text=(
                f"Export ledgers list {alloy} as the sole strategic metal mined "
                f"within {city} limits after {year}."
            ),
        ),
    ]


def control_missing_one_hop(question: dict[str, Any]) -> list[ReaderPassage]:
    """E: keep only the first gold passage (drop second hop)."""
    gold = gold_passages(question)
    if not gold:
        return []
    keep = gold[:1]
    # Relabel S1 only
    return [
        ReaderPassage(
            label="S1",
            title=keep[0].title,
            text=keep[0].text,
            doc_id=keep[0].doc_id,
            chunk_id=keep[0].chunk_id,
        )
    ]


CONTROLS: dict[str, Any] = {
    "remove_gold": control_remove_gold,
    "distractors": control_distractors,
    "swap_titles": control_swap_labels,
    "counterfactual": control_counterfactual,
    "missing_one_hop": control_missing_one_hop,
}

# Expected behavior for scoring.
CONTROL_EXPECT: dict[str, dict[str, Any]] = {
    "remove_gold": {"must_abstain": True, "credit_answer_f1": False},
    "distractors": {"must_abstain": True, "credit_answer_f1": False},
    "swap_titles": {
        # Gold text still present under wrong titles — answer may be recoverable,
        # but citation titles must not be trusted as provenance. We still require
        # quote↔label integrity; F1 alone is not success without support.
        "must_abstain": False,
        "credit_answer_f1": True,
        "require_supported": True,
    },
    "counterfactual": {
        # Question is still the Hotpot question; counterfactual passages cannot
        # answer it → must abstain (not invent Hotpot gold from pretrained knowledge).
        "must_abstain": True,
        "credit_answer_f1": False,
    },
    "missing_one_hop": {"must_abstain": True, "credit_answer_f1": False},
}


__all__ = ["CONTROLS", "CONTROL_EXPECT", "gold_passages"]
