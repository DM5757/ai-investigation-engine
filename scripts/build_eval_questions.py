"""Build Phase 7 evaluation question set (≥40, target ~70).

Sources:
  - HotpotQA distractor validation (multi-hop / factual) filtered to corpus titles
  - Synthetic enterprise truth (contradiction / unanswerable / multi-doc)

Usage:
  uv run python scripts/build_eval_questions.py
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


def load_corpus_titles(limit: int | None = None) -> set[str]:
    titles: set[str] = set()
    for i, rec in enumerate(iter_jsonl(RAW_CORPUS)):
        titles.add(str(rec.get("title") or ""))
        if limit is not None and i + 1 >= limit:
            break
    titles.discard("")
    return titles


def _hotpot_from_parquet(titles: set[str], *, max_q: int, seed: int) -> list[dict[str, Any]]:
    cache = ROOT / "data" / "cache" / "hotpot_hf" / "validation-00000-of-00001.parquet"
    if not cache.exists():
        print(f"WARN: missing {cache}; skipping Hotpot questions", file=sys.stderr)
        return []
    import pyarrow.parquet as pq

    rng = random.Random(seed)
    candidates: list[dict[str, Any]] = []
    pf = pq.ParquetFile(cache)
    for batch in pf.iter_batches(batch_size=256):
        rows = batch.to_pydict()
        n = len(rows.get("question") or [])
        for i in range(n):
            question = str(rows["question"][i])
            answer = str(rows["answer"][i])
            # supporting_facts: typically list of [title, sent_id] or struct
            sf = rows.get("supporting_facts")
            gold_titles: list[str] = []
            if sf is not None:
                cell = sf[i]
                # pyarrow may yield {"title": [...], "sent_id": [...]} or list of pairs
                if isinstance(cell, dict) and "title" in cell:
                    gold_titles = [str(t) for t in cell["title"]]
                elif isinstance(cell, list):
                    for item in cell:
                        if isinstance(item, (list, tuple)) and item:
                            gold_titles.append(str(item[0]))
                        elif isinstance(item, dict) and "title" in item:
                            gold_titles.append(str(item["title"]))
            gold_titles = list(dict.fromkeys(gold_titles))
            if len(gold_titles) < 2:
                continue
            if not all(t in titles for t in gold_titles):
                continue
            qtype = "multi_hop" if len(gold_titles) >= 2 else "factual"
            candidates.append(
                {
                    "id": f"hotpot_{len(candidates):04d}",
                    "question": question,
                    "gold_answer": answer,
                    "gold_doc_titles": gold_titles,
                    "gold_external_keys": [f"hotpotqa:{t}" for t in gold_titles],
                    "question_type": qtype,
                    "split_hint": "hotpot",
                    "provenance": {
                        "dataset": "hotpotqa/hotpot_qa",
                        "config": "distractor",
                        "split": "validation",
                        "license": "CC-BY-SA-4.0",
                    },
                }
            )
    rng.shuffle(candidates)
    # Prefer multi_hop; keep factual (single-answer) mix
    multi = [c for c in candidates if c["question_type"] == "multi_hop"]
    simple = [c for c in candidates if c["question_type"] != "multi_hop"]
    # Promote some multi as factual_simple when answer is short entity
    out: list[dict[str, Any]] = []
    for c in multi:
        if len(out) >= max_q:
            break
        # Mark ~40% as multi_doc explicitly
        if len(out) % 5 < 2:
            c = {**c, "question_type": "multi_doc"}
        out.append(c)
    for c in simple:
        if len(out) >= max_q:
            break
        c = {**c, "question_type": "factual"}
        out.append(c)
    return out


def _synthetic_questions(truth: dict[str, Any]) -> list[dict[str, Any]]:
    qs: list[dict[str, Any]] = []
    # Multi-doc causal / investigation style
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
            "split_hint": "synthetic",
            "provenance": {"source": "chunking_gold_spans"},
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
                "split_hint": "synthetic",
                "provenance": {"contradiction_id": c.get("id"), "claims": claims},
            }
        )
    for topic in truth.get("unanswerable_topics") or []:
        qs.append(
            {
                "id": f"syn_unans_{len(qs)}",
                "question": str(topic),
                "gold_answer": "INSUFFICIENT",
                "gold_doc_titles": [],
                "gold_external_keys": [],
                "question_type": "unanswerable",
                "expected_status": "insufficient",
                "split_hint": "synthetic",
                "provenance": {"source": "unanswerable_topics"},
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
                "split_hint": "synthetic",
                "provenance": {"incomplete_id": inc.get("id")},
            }
        )
    # Extra multi-step / multi-doc synthetics for coverage
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
            "split_hint": "synthetic",
            "provenance": {"source": "synthetic_enterprise"},
        }
    )
    return qs


def split_dev_test(
    questions: list[dict[str, Any]], *, seed: int, test_ratio: float = 0.6
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for q in questions:
        by_type.setdefault(str(q.get("question_type") or "other"), []).append(q)
    dev: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for items in by_type.values():
        rng.shuffle(items)
        n_test = max(1, int(round(len(items) * test_ratio))) if len(items) > 1 else len(items)
        # Prefer more in test for final report; keep at least one in dev when possible
        if len(items) == 1:
            test.extend(items)
        else:
            test.extend(items[:n_test])
            dev.extend(items[n_test:])
    rng.shuffle(dev)
    rng.shuffle(test)
    return dev, test


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--hotpot-max", type=int, default=55)
    parser.add_argument(
        "--corpus-title-limit",
        type=int,
        default=None,
        help="Only use first N corpus titles (default: all 55k titles in JSONL)",
    )
    args = parser.parse_args()
    ensure_dirs()
    (ROOT / "eval" / "questions").mkdir(parents=True, exist_ok=True)

    print("loading corpus titles…", flush=True)
    titles = load_corpus_titles(args.corpus_title_limit)
    print(f"corpus titles={len(titles)}", flush=True)

    hotpot = _hotpot_from_parquet(titles, max_q=args.hotpot_max, seed=args.seed)
    truth = json.loads(SYNTHETIC_TRUTH.read_text(encoding="utf-8"))
    synthetic = _synthetic_questions(truth)
    questions = synthetic + hotpot

    # Ensure type coverage counts
    type_counts: dict[str, int] = {}
    for q in questions:
        t = str(q.get("question_type"))
        type_counts[t] = type_counts.get(t, 0) + 1

    for i, q in enumerate(questions):
        q["index"] = i
        q.setdefault("gold_external_keys", [])
        q.setdefault("gold_doc_paths", [])

    dev, test = split_dev_test(questions, seed=args.seed)
    for q in dev:
        q["split"] = "dev"
    for q in test:
        q["split"] = "test"

    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "n_questions": len(questions),
        "type_counts": type_counts,
        "corpus_titles_considered": len(titles),
        "corpus_manifest_sha256": None,
        "meets_min_40": len(questions) >= 40,
        "questions": questions,
    }
    if CORPUS_MANIFEST.exists():
        man = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
        payload["corpus_manifest_sha256"] = man.get("sha256")

    write_json(OUT_PATH, payload)
    write_json(DEV_PATH, {"split": "dev", "n": len(dev), "questions": dev})
    write_json(TEST_PATH, {"split": "test", "n": len(test), "questions": test})
    print(
        f"wrote {len(questions)} questions (dev={len(dev)} test={len(test)}) "
        f"types={type_counts} -> {OUT_PATH.as_posix()}",
        flush=True,
    )
    if len(questions) < 40:
        print("ERROR: fewer than 40 questions", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
