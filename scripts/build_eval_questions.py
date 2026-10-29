"""Build Phase 7 evaluation question set (≥40, target ~70).

Sources:
  - HotpotQA distractor validation + train (multi-hop / factual)
  - Synthetic enterprise truth (contradiction / unanswerable / multi-doc)

Usage:
  uv run python scripts/build_eval_questions.py
  uv run python scripts/build_eval_questions.py --require-active
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

from scripts._phase6_common import (  # noqa: E402
    CORPUS_MANIFEST,
    RAW_CORPUS,
    SYNTHETIC_TRUTH,
    ensure_dirs,
    iter_jsonl,
    write_json,
)

OUT_PATH = ROOT / "eval" / "questions" / "eval_set.json"
DEV_PATH = ROOT / "eval" / "questions" / "dev_split.json"
TEST_PATH = ROOT / "eval" / "questions" / "test_split.json"
HOTPOT_CACHE = ROOT / "data" / "cache" / "hotpot_hf"


def load_corpus_titles(limit: int | None = None) -> set[str]:
    titles: set[str] = set()
    for i, rec in enumerate(iter_jsonl(RAW_CORPUS)):
        titles.add(str(rec.get("title") or ""))
        if limit is not None and i + 1 >= limit:
            break
    titles.discard("")
    return titles


def load_active_hotpot_titles() -> tuple[set[str], dict[str, Any]]:
    """Titles for ACTIVE hotpotqa:* documents currently in Neon."""
    from sqlalchemy import select

    from app.config import get_settings
    from app.db.models import Document, DocumentStatus
    from scripts._phase6_common import neon_doc_counts, open_session

    settings = get_settings()
    session = open_session(settings)
    try:
        rows = session.scalars(
            select(Document).where(Document.status == DocumentStatus.ACTIVE)
        ).all()
        titles: set[str] = set()
        for doc in rows:
            if doc.external_key and str(doc.external_key).startswith("hotpotqa:"):
                titles.add(str(doc.external_key)[len("hotpotqa:") :])
            elif doc.title:
                titles.add(doc.title)
        meta = {
            "active_documents": len(rows),
            "hotpot_titles": len(titles),
            "neon_counts": neon_doc_counts(settings),
        }
        return titles, meta
    finally:
        session.close()


def _extract_gold_titles(cell: Any) -> list[str]:
    gold_titles: list[str] = []
    if isinstance(cell, dict) and "title" in cell:
        gold_titles = [str(t) for t in cell["title"]]
    elif isinstance(cell, list):
        for item in cell:
            if isinstance(item, (list, tuple)) and item:
                gold_titles.append(str(item[0]))
            elif isinstance(item, dict) and "title" in item:
                gold_titles.append(str(item["title"]))
    return list(dict.fromkeys(gold_titles))


def _hotpot_from_parquets(
    titles: set[str],
    *,
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
    if not files:
        print(f"WARN: no Hotpot parquet under {HOTPOT_CACHE}", file=sys.stderr)
        return []

    for split_name, path in files:
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=512):
            rows = batch.to_pydict()
            n = len(rows.get("question") or [])
            for i in range(n):
                supporting = rows.get("supporting_facts")
                gold_titles = _extract_gold_titles(
                    rows["supporting_facts"][i] if supporting is not None else None
                )
                if len(gold_titles) < 2:
                    continue
                if not all(t in titles for t in gold_titles):
                    continue
                answer = str(rows["answer"][i])
                qtype = "multi_hop"
                # Short entity answers labeled factual for type mix (still multi-doc gold).
                if len(answer.split()) <= 4:
                    qtype = "factual"
                candidates.append(
                    {
                        "id": f"hotpot_{split_name}_{len(candidates):04d}",
                        "question": str(rows["question"][i]),
                        "gold_answer": answer,
                        "gold_doc_titles": gold_titles,
                        "gold_external_keys": [f"hotpotqa:{t}" for t in gold_titles],
                        "question_type": qtype,
                        "requires_all_gold_docs": True,
                        "split_hint": "hotpot",
                        "provenance": {
                            "dataset": "hotpotqa/hotpot_qa",
                            "config": "distractor",
                            "split": split_name,
                            "license": "CC-BY-SA-4.0",
                            "title_filter": "active_neon"
                            if "active" in str(titles)
                            else "corpus_jsonl",
                        },
                    }
                )

    rng.shuffle(candidates)
    # Rebalance types: promote some multi_hop-length answers to multi_doc
    out: list[dict[str, Any]] = []
    for c in candidates:
        if len(out) >= max_q:
            break
        item = dict(c)
        if item["question_type"] == "multi_hop" and len(out) % 3 == 0:
            item["question_type"] = "multi_doc"
        elif item["question_type"] == "factual" and len(item["gold_doc_titles"]) >= 2:
            # Keep factual label but note multi-evidence
            item["multi_evidence"] = True
        out.append(item)
    return out


def _synthetic_questions(truth: dict[str, Any]) -> list[dict[str, Any]]:
    qs: list[dict[str, Any]] = []
    qs.append(
        {
            "id": "syn_multi_payment_march",
            "question": (
                "Which system changes caused disruptions in payment processing in March, "
                "which services were affected, and which documents support this?"
            ),
            "gold_answer": (
                "AuthGateway JWT TTL misconfiguration and related deploy changes "
                "disrupted payment processing; payment and auth services affected."
            ),
            "gold_doc_titles": [
                "incident_march",
                "change_log",
                "status_update",
                "postmortem_draft",
            ],
            "gold_external_keys": [],
            "gold_doc_paths": [
                "data/synthetic/incident_march.md",
                "data/synthetic/change_log.html",
                "data/synthetic/status_update.txt",
                "data/synthetic/postmortem_draft.docx",
            ],
            "question_type": "multi_doc",
            "requires_all_gold_docs": False,
            "split_hint": "synthetic",
            "provenance": {"source": "synthetic_truth", "seed": truth.get("seed")},
        }
    )
    qs.append(
        {
            "id": "syn_factual_alpha_marker",
            "question": "Where is the ALPHA-OUTAGE-0810 marker described?",
            "gold_answer": "ALPHA-OUTAGE-0810",
            "gold_doc_titles": ["long_architecture"],
            "gold_doc_paths": ["data/synthetic/long_architecture.md"],
            "gold_external_keys": [],
            "question_type": "factual",
            "requires_all_gold_docs": True,
            "split_hint": "synthetic",
            "provenance": {"source": "chunking_gold_spans"},
        }
    )
    qs.append(
        {
            "id": "syn_factual_beta_marker",
            "question": "Where is the BETA-POOL-EXHAUST marker described?",
            "gold_answer": "BETA-POOL-EXHAUST",
            "gold_doc_titles": ["long_architecture"],
            "gold_doc_paths": ["data/synthetic/long_architecture.md"],
            "gold_external_keys": [],
            "question_type": "factual",
            "requires_all_gold_docs": True,
            "split_hint": "synthetic",
            "provenance": {"source": "chunking_gold_spans"},
        }
    )
    qs.append(
        {
            "id": "syn_factual_jwt",
            "question": "What misconfiguration on AuthGateway was reported in the March incident?",
            "gold_answer": "misconfigured JWT TTL",
            "gold_doc_paths": ["data/synthetic/incident_march.md"],
            "gold_doc_titles": ["incident_march"],
            "gold_external_keys": [],
            "question_type": "factual",
            "requires_all_gold_docs": True,
            "split_hint": "synthetic",
            "provenance": {"source": "synthetic"},
        }
    )
    qs.append(
        {
            "id": "syn_factual_pool",
            "question": (
                "What database pool problem is mentioned in the change log "
                "as a root cause candidate?"
            ),
            "gold_answer": "Neon connection pool exhaustion",
            "gold_doc_paths": ["data/synthetic/change_log.html"],
            "gold_doc_titles": ["change_log"],
            "gold_external_keys": [],
            "question_type": "factual",
            "requires_all_gold_docs": True,
            "split_hint": "synthetic",
            "provenance": {"source": "synthetic"},
        }
    )
    qs.append(
        {
            "id": "syn_multi_docs_services",
            "question": (
                "Which services were affected by the March payment disruption according to "
                "incident and status documents?"
            ),
            "gold_answer": "payment and authentication services",
            "gold_doc_paths": [
                "data/synthetic/incident_march.md",
                "data/synthetic/status_update.txt",
            ],
            "gold_doc_titles": ["incident_march", "status_update"],
            "gold_external_keys": [],
            "question_type": "multi_doc",
            "requires_all_gold_docs": True,
            "split_hint": "synthetic",
            "provenance": {"source": "synthetic"},
        }
    )
    for c in truth.get("contradictions") or []:
        topic = str(c.get("topic") or c.get("id"))
        claims = c.get("claims") or []
        docs = [str(x.get("doc") or "") for x in claims]
        qs.append(
            {
                "id": f"syn_contra_{c.get('id')}",
                "question": f"What do the documents say about {topic}? Note any contradictions.",
                "gold_answer": "CONFLICTING",
                "gold_doc_paths": docs,
                "gold_doc_titles": [Path(d).stem for d in docs if d],
                "gold_external_keys": [],
                "question_type": "contradiction",
                "expected_status": "conflicting",
                "requires_all_gold_docs": True,
                "split_hint": "synthetic",
                "provenance": {"contradiction_id": c.get("id"), "claims": claims},
            }
        )
    qs.append(
        {
            "id": "syn_contra_deploy",
            "question": (
                "At what time was auth-gateway deployed on 2024-03-12? "
                "Report contradictions if present."
            ),
            "gold_answer": "CONFLICTING",
            "gold_doc_paths": [
                "data/synthetic/incident_march.md",
                "data/synthetic/change_log.html",
            ],
            "gold_doc_titles": ["incident_march", "change_log"],
            "gold_external_keys": [],
            "question_type": "contradiction",
            "expected_status": "conflicting",
            "requires_all_gold_docs": True,
            "split_hint": "synthetic",
            "provenance": {"source": "c1"},
        }
    )
    for topic in truth.get("unanswerable_topics") or []:
        qs.append(
            {
                "id": f"syn_unans_{abs(hash(topic)) % 10_000}",
                "question": str(topic),
                "gold_answer": "INSUFFICIENT",
                "gold_doc_titles": [],
                "gold_external_keys": [],
                "question_type": "unanswerable",
                "expected_status": "insufficient",
                "requires_all_gold_docs": False,
                "split_hint": "synthetic",
                "provenance": {"source": "unanswerable_topics"},
            }
        )
    qs.append(
        {
            "id": "syn_unans_cpu",
            "question": "What was FraudScorer CPU usage during the incident?",
            "gold_answer": "INSUFFICIENT",
            "gold_doc_titles": [],
            "gold_external_keys": [],
            "question_type": "unanswerable",
            "expected_status": "insufficient",
            "requires_all_gold_docs": False,
            "split_hint": "synthetic",
            "provenance": {"source": "unanswerable"},
        }
    )
    for inc in truth.get("incomplete") or []:
        qs.append(
            {
                "id": f"syn_incomplete_{inc.get('id')}",
                "question": f"What is the missing detail regarding: {inc.get('missing')}?",
                "gold_answer": "INSUFFICIENT",
                "gold_doc_paths": [str(inc.get("doc") or "")],
                "gold_doc_titles": [Path(str(inc.get("doc") or "")).stem],
                "gold_external_keys": [],
                "question_type": "unanswerable",
                "expected_status": "insufficient",
                "requires_all_gold_docs": False,
                "split_hint": "synthetic",
                "provenance": {"incomplete_id": inc.get("id")},
            }
        )
    qs.append(
        {
            "id": "syn_multistep_latency",
            "question": (
                "According to the latency metrics and status updates, which components "
                "showed elevated latency during the March incident?"
            ),
            "gold_answer": "payment and auth-related components",
            "gold_doc_paths": [
                "data/synthetic/latency_metrics.csv",
                "data/synthetic/status_update.txt",
            ],
            "gold_doc_titles": ["latency_metrics", "status_update"],
            "gold_external_keys": [],
            "question_type": "multi_step",
            "requires_all_gold_docs": True,
            "split_hint": "synthetic",
            "provenance": {"source": "synthetic_enterprise"},
        }
    )
    qs.append(
        {
            "id": "syn_exec_summary",
            "question": "What does the executive summary say about the March outage impact?",
            "gold_answer": "payment processing disruptions",
            "gold_doc_paths": ["data/synthetic/exec_summary.pdf"],
            "gold_doc_titles": ["exec_summary"],
            "gold_external_keys": [],
            "question_type": "factual",
            "requires_all_gold_docs": True,
            "split_hint": "synthetic",
            "provenance": {"source": "synthetic_enterprise"},
        }
    )
    return qs


def split_dev_test(
    questions: list[dict[str, Any]], *, seed: int, test_ratio: float = 0.65
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for q in questions:
        by_type.setdefault(str(q.get("question_type") or "other"), []).append(q)
    dev: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for items in by_type.values():
        rng.shuffle(items)
        if len(items) == 1:
            test.extend(items)
            continue
        n_test = max(1, int(round(len(items) * test_ratio)))
        test.extend(items[:n_test])
        dev.extend(items[n_test:])
    rng.shuffle(dev)
    rng.shuffle(test)
    return dev, test


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--hotpot-max", type=int, default=80)
    parser.add_argument(
        "--require-active",
        action="store_true",
        help="Only include Hotpot questions whose ALL gold titles are ACTIVE in Neon",
    )
    parser.add_argument(
        "--corpus-title-limit",
        type=int,
        default=None,
        help="Only use first N corpus titles (ignored with --require-active)",
    )
    parser.add_argument(
        "--splits",
        type=str,
        default="validation,train",
        help="Hotpot parquet splits to scan",
    )
    args = parser.parse_args()
    ensure_dirs()
    (ROOT / "eval" / "questions").mkdir(parents=True, exist_ok=True)

    active_meta: dict[str, Any] | None = None
    if args.require_active:
        print("loading ACTIVE Hotpot titles from Neon…", flush=True)
        titles, active_meta = load_active_hotpot_titles()
        print(
            f"active hotpot titles={len(titles)} docs={active_meta.get('active_documents')}",
            flush=True,
        )
    else:
        print("loading corpus titles…", flush=True)
        titles = load_corpus_titles(args.corpus_title_limit)
        print(f"corpus titles={len(titles)}", flush=True)

    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    hotpot = _hotpot_from_parquets(
        titles, max_q=args.hotpot_max, seed=args.seed, splits=splits
    )
    truth = json.loads(SYNTHETIC_TRUTH.read_text(encoding="utf-8"))
    synthetic = _synthetic_questions(truth)
    questions = synthetic + hotpot

    # Dedup by question text
    seen_q: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for q in questions:
        key = str(q.get("question") or "").strip().lower()
        if key in seen_q:
            continue
        seen_q.add(key)
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
        q.setdefault("requires_all_gold_docs", True)

    dev, test = split_dev_test(questions, seed=args.seed)
    for q in dev:
        q["split"] = "dev"
    for q in test:
        q["split"] = "test"

    payload: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "n_questions": len(questions),
        "type_counts": type_counts,
        "title_filter": "active_neon" if args.require_active else "corpus_jsonl",
        "active_meta": active_meta,
        "corpus_titles_considered": len(titles),
        "corpus_manifest_sha256": None,
        "meets_min_40": len(questions) >= 40,
        "questions": questions,
        "notes": (
            "When title_filter=active_neon, Hotpot golds are guaranteed indexed at build time. "
            "Re-run with --require-active after more ingest to expand the Hotpot subset."
        ),
    }
    if CORPUS_MANIFEST.exists():
        man = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
        payload["corpus_manifest_sha256"] = man.get("sha256")

    write_json(OUT_PATH, payload)
    write_json(DEV_PATH, {"split": "dev", "n": len(dev), "questions": dev})
    write_json(TEST_PATH, {"split": "test", "n": len(test), "questions": test})
    print(
        f"wrote {len(questions)} questions (dev={len(dev)} test={len(test)}) "
        f"types={type_counts} filter={payload['title_filter']} -> {OUT_PATH.as_posix()}",
        flush=True,
    )
    if len(questions) < 40:
        print("ERROR: fewer than 40 questions", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
