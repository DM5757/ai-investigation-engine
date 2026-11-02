"""Build a fresh held-out eval set that does not overlap the legacy test set.

- Uses HotpotQA native ``id`` + ``type`` (bridge/comparison).
- Excludes any question text already present in ``eval/questions/eval_set.json``.
- Requires all gold titles ACTIVE in Neon (same corpus constraint).
- Adds expanded synthetic unanswerable + contradiction items.
- Writes ``eval/questions/heldout_v1.json`` marked frozen (do not tune against).

Usage:
  uv run python scripts/build_heldout_eval.py --require-active --hotpot-max 80
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._phase6_common import ensure_dirs, write_json  # noqa: E402
from scripts.build_eval_questions import (  # noqa: E402
    HOTPOT_CACHE,
    SYNTHETIC_TRUTH,
    _extract_gold_titles,
    load_active_hotpot_titles,
)

LEGACY_SET = ROOT / "eval" / "questions" / "eval_set.json"
OUT_PATH = ROOT / "eval" / "questions" / "heldout_v1.json"
OUT_DEV = ROOT / "eval" / "questions" / "heldout_v1_dev.json"
OUT_TEST = ROOT / "eval" / "questions" / "heldout_v1_test.json"


def _legacy_question_texts() -> set[str]:
    if not LEGACY_SET.is_file():
        return set()
    payload = json.loads(LEGACY_SET.read_text(encoding="utf-8"))
    return {
        str(q.get("question") or "").strip().lower()
        for q in payload.get("questions") or []
    }


def _hotpot_type_to_question_type(hotpot_type: str) -> str:
    t = (hotpot_type or "").strip().lower()
    if t == "comparison":
        return "multi_doc"
    if t == "bridge":
        return "multi_hop"
    return "multi_hop"


def _scan_unused_hotpot(
    titles: set[str],
    *,
    exclude_questions: set[str],
    max_q: int,
    seed: int,
    splits: list[str],
) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    rng = random.Random(seed)
    candidates: list[dict[str, Any]] = []
    files: list[tuple[str, Path]] = []
    if "validation" in splits:
        p = HOTPOT_CACHE / "validation-00000-of-00001.parquet"
        if p.exists():
            files.append(("validation", p))
    if "train" in splits:
        for name in ("train-00000-of-00002.parquet", "train-00001-of-00002.parquet"):
            p = HOTPOT_CACHE / name
            if p.exists():
                files.append(("train", p))
    for split_name, path in files:
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=512):
            rows = batch.to_pydict()
            n = len(rows.get("question") or [])
            for i in range(n):
                qtext = str(rows["question"][i]).strip()
                if qtext.lower() in exclude_questions:
                    continue
                supporting = rows.get("supporting_facts")
                gold_titles = _extract_gold_titles(
                    rows["supporting_facts"][i] if supporting is not None else None
                )
                if len(gold_titles) < 2:
                    continue
                if not all(t in titles for t in gold_titles):
                    continue
                native_id = str(rows["id"][i]) if rows.get("id") is not None else ""
                hotpot_type = str(rows["type"][i]) if rows.get("type") is not None else ""
                candidates.append(
                    {
                        "id": (
                            f"heldout_hotpot_"
                            f"{native_id or f'{split_name}_{len(candidates):04d}'}"
                        ),
                        "question": qtext,
                        "gold_answer": str(rows["answer"][i]),
                        "gold_doc_titles": gold_titles,
                        "gold_external_keys": [f"hotpotqa:{t}" for t in gold_titles],
                        "question_type": _hotpot_type_to_question_type(hotpot_type),
                        "hotpot_type": hotpot_type or None,
                        "hotpot_level": (
                            str(rows["level"][i]) if rows.get("level") is not None else None
                        ),
                        "requires_all_gold_docs": True,
                        "split_hint": "heldout_hotpot",
                        "provenance": {
                            "dataset": "hotpotqa/hotpot_qa",
                            "config": "distractor",
                            "split": split_name,
                            "native_id": native_id,
                            "hotpot_type": hotpot_type,
                            "license": "CC-BY-SA-4.0",
                            "title_filter": "active_neon",
                            "heldout": True,
                        },
                    }
                )
    rng.shuffle(candidates)
    return candidates[:max_q]


def _extra_synthetic() -> list[dict[str, Any]]:
    """Expand unanswerable / contradiction coverage beyond the legacy two-of-each."""
    truth = json.loads(SYNTHETIC_TRUTH.read_text(encoding="utf-8"))
    qs: list[dict[str, Any]] = []
    # Unanswerable — attribute absent from synthetic corpus.
    qs.append(
        {
            "id": "heldout_unans_disk_pressure",
            "question": (
                "What was the disk utilization percentage on FraudScorer "
                "during the March outage?"
            ),
            "gold_answer": "INSUFFICIENT",
            "gold_doc_titles": [],
            "gold_external_keys": [],
            "gold_doc_paths": [],
            "question_type": "unanswerable",
            "expected_status": "insufficient",
            "requires_all_gold_docs": False,
            "split_hint": "heldout_synthetic",
            "provenance": {"source": "heldout_synthetic", "grounding": "attribute_absent"},
        }
    )
    qs.append(
        {
            "id": "heldout_unans_approver_name",
            "question": "Who approved the emergency rollback of auth-gateway on 2024-03-12?",
            "gold_answer": "INSUFFICIENT",
            "gold_doc_titles": [],
            "gold_external_keys": [],
            "gold_doc_paths": [],
            "question_type": "unanswerable",
            "expected_status": "insufficient",
            "requires_all_gold_docs": False,
            "split_hint": "heldout_synthetic",
            "provenance": {
                "source": "heldout_synthetic",
                "grounding": "redacted_or_absent_approver",
            },
        }
    )
    qs.append(
        {
            "id": "heldout_unans_customer_count",
            "question": "How many paying customers were affected by the March payment outage?",
            "gold_answer": "INSUFFICIENT",
            "gold_doc_titles": [],
            "gold_external_keys": [],
            "gold_doc_paths": [],
            "question_type": "unanswerable",
            "expected_status": "insufficient",
            "requires_all_gold_docs": False,
            "split_hint": "heldout_synthetic",
            "provenance": {"source": "heldout_synthetic", "grounding": "metric_absent"},
        }
    )
    # Contradiction — reuse planted deploy-time conflict with alternate phrasing.
    qs.append(
        {
            "id": "heldout_contra_deploy_alt",
            "question": (
                "According to the change log and the incident report, when was "
                "auth-gateway deployed on 2024-03-12? Identify any disagreement."
            ),
            "gold_answer": "CONFLICTING",
            "gold_doc_titles": ["change_log", "incident_march"],
            "gold_doc_paths": [
                "data/synthetic/change_log.html",
                "data/synthetic/incident_march.md",
            ],
            "gold_external_keys": [],
            "question_type": "contradiction",
            "expected_status": "conflicting",
            "requires_all_gold_docs": False,
            "split_hint": "heldout_synthetic",
            "provenance": {
                "source": "heldout_synthetic",
                "grounding": "planted_08:10_vs_14:00",
                "truth_seed": truth.get("seed"),
            },
        }
    )
    qs.append(
        {
            "id": "heldout_contra_root_cause",
            "question": (
                "Do the March incident documents agree on the root cause of the "
                "payment disruption? Note contradictions if present."
            ),
            "gold_answer": "CONFLICTING",
            "gold_doc_titles": ["incident_march", "postmortem_draft", "status_update"],
            "gold_doc_paths": [
                "data/synthetic/incident_march.md",
                "data/synthetic/postmortem_draft.docx",
                "data/synthetic/status_update.txt",
            ],
            "gold_external_keys": [],
            "question_type": "contradiction",
            "expected_status": "conflicting",
            "requires_all_gold_docs": False,
            "split_hint": "heldout_synthetic",
            "provenance": {
                "source": "heldout_synthetic",
                "grounding": "causal_conflict_probe",
            },
        }
    )
    return qs


def _split(
    questions: list[dict[str, Any]], *, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dev for tuning diagnostics; test frozen for final reporting."""
    rng = random.Random(seed)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for q in questions:
        by_type.setdefault(str(q.get("question_type") or "other"), []).append(q)
    dev: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for items in by_type.values():
        rng.shuffle(items)
        if len(items) == 1:
            test.append(items[0])
            continue
        # ~30% dev / 70% test — keep most mass on frozen test.
        n_dev = max(1, int(round(len(items) * 0.3)))
        if n_dev >= len(items):
            n_dev = len(items) - 1
        dev.extend(items[:n_dev])
        test.extend(items[n_dev:])
    rng.shuffle(dev)
    rng.shuffle(test)
    return dev, test


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--hotpot-max", type=int, default=80)
    parser.add_argument("--require-active", action="store_true", default=True)
    parser.add_argument("--splits", type=str, default="validation,train")
    args = parser.parse_args()
    ensure_dirs()
    (ROOT / "eval" / "questions").mkdir(parents=True, exist_ok=True)

    exclude = _legacy_question_texts()
    print(f"legacy questions excluded={len(exclude)}", flush=True)
    print("loading ACTIVE Hotpot titles from Neon…", flush=True)
    titles, active_meta = load_active_hotpot_titles()
    print(f"active titles={len(titles)}", flush=True)

    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    hotpot = _scan_unused_hotpot(
        titles,
        exclude_questions=exclude,
        max_q=args.hotpot_max,
        seed=args.seed,
        splits=splits,
    )
    synthetic = _extra_synthetic()
    # Drop synthetic questions that collide with legacy text.
    synthetic = [
        q
        for q in synthetic
        if str(q.get("question") or "").strip().lower() not in exclude
    ]
    questions = synthetic + hotpot
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for q in questions:
        key = str(q.get("question") or "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(q)
    questions = deduped

    type_counts: dict[str, int] = {}
    for q in questions:
        t = str(q.get("question_type"))
        type_counts[t] = type_counts.get(t, 0) + 1

    for i, q in enumerate(questions):
        q["index"] = i
        q.setdefault("gold_external_keys", [])
        q.setdefault("gold_doc_paths", [])

    dev, test = _split(questions, seed=args.seed)
    for q in dev:
        q["split"] = "dev"
        q["frozen"] = False
    for q in test:
        q["split"] = "test"
        q["frozen"] = True

    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "n_questions": len(questions),
        "n_dev": len(dev),
        "n_test": len(test),
        "type_counts": type_counts,
        "title_filter": "active_neon",
        "active_meta": active_meta,
        "excludes_legacy_eval_set": True,
        "legacy_eval_set": str(LEGACY_SET.as_posix()),
        "legacy_questions_excluded": len(exclude),
        "methodology": {
            "hotpot_labels": "native Hotpot type field (bridge→multi_hop, comparison→multi_doc)",
            "legacy_set_status": "development/diagnostic only; do not treat as clean held-out",
            "tuning_rule": "Do not tune against frozen heldout_v1 test answers",
            "unanswerable_contradiction_note": (
                "Expanded synthetic coverage; still small-n — do not claim "
                "high confidence from two legacy cases alone."
            ),
        },
        "questions": questions,
    }
    write_json(OUT_PATH, payload)
    write_json(OUT_DEV, {"split": "dev", "n": len(dev), "questions": dev})
    write_json(OUT_TEST, {"split": "test", "frozen": True, "n": len(test), "questions": test})
    print(
        f"wrote heldout_v1 n={len(questions)} (dev={len(dev)} test={len(test)}) "
        f"types={type_counts} -> {OUT_PATH.as_posix()}",
        flush=True,
    )


if __name__ == "__main__":
    main()
