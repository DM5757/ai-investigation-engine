"""Build Phase B expanded, disjoint evaluation benchmark.

Targets (subject to eligible Active-gold Hotpot supply):
  - >=150 development questions
  - >=300 sealed test questions
Excludes legacy eval_set, heldout_v1, and curated demo question texts.
Stores Hotpot gold paragraphs for oracle-reader experiments.
Adds separate robustness packs (ablated unanswerable, contradiction, controls).

Usage:
  uv run python scripts/build_phase_b_benchmark.py --dev-n 150 --test-n 300
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
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

OUT_DIR = ROOT / "eval" / "questions"
MANIFEST = OUT_DIR / "phase_b_bench_v1_manifest.json"
OUT_ALL = OUT_DIR / "phase_b_bench_v1.json"
OUT_DEV = OUT_DIR / "phase_b_bench_v1_dev.json"
OUT_TEST = OUT_DIR / "phase_b_bench_v1_test_sealed.json"
OUT_ROBUST = OUT_DIR / "phase_b_bench_v1_robustness.json"

DEMO_SNIPPETS = [
    "roanoke–blacksburg regional airport",
    "roanoke-blacksburg regional airport",
    "ohio state university or california state university, dominguez hills",
    "michael lent is best known",
    "mary robinson was nicknamed",
    "auth-gateway deploy time",
    "fraudscorer cpu usage",
    "roanoke colony disappearance",
]

_WS = re.compile(r"\s+")


def _norm_q(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def _token_set(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _near_dup(a: str, b: str, *, thresh: float = 0.92) -> bool:
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return (inter / union) >= thresh


def _load_exclusions() -> tuple[set[str], set[str]]:
    texts: set[str] = set()
    native_ids: set[str] = set()
    for path in (
        OUT_DIR / "eval_set.json",
        OUT_DIR / "heldout_v1.json",
        OUT_DIR / "heldout_v1_test.json",
        OUT_DIR / "heldout_v1_dev.json",
    ):
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for q in payload.get("questions") or []:
            texts.add(_norm_q(str(q.get("question") or "")))
            nid = (q.get("provenance") or {}).get("native_id")
            if nid:
                native_ids.add(str(nid))
            qid = str(q.get("id") or "")
            if qid.startswith("heldout_hotpot_"):
                native_ids.add(qid.replace("heldout_hotpot_", "", 1))
    for snip in DEMO_SNIPPETS:
        texts.add(_norm_q(snip))
    return texts, native_ids


def _hotpot_type_to_question_type(hotpot_type: str) -> str:
    t = (hotpot_type or "").strip().lower()
    if t == "comparison":
        return "multi_doc"
    return "multi_hop"


def _gold_paragraphs(
    context: dict[str, Any],
    gold_titles: list[str],
    supporting: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Full paragraphs for gold titles (oracle evidence); include SF sentence ids."""
    titles = list(context.get("title") or [])
    sentences = list(context.get("sentences") or [])
    title_to_sents: dict[str, list[str]] = {}
    for title, sents in zip(titles, sentences, strict=False):
        title_to_sents[str(title)] = [str(s) for s in (sents or [])]

    sf_map: dict[str, list[int]] = {}
    if isinstance(supporting, dict):
        sf_titles = list(supporting.get("title") or [])
        sf_ids = list(supporting.get("sent_id") or [])
        for t, sid in zip(sf_titles, sf_ids, strict=False):
            sf_map.setdefault(str(t), []).append(int(sid))

    out: list[dict[str, Any]] = []
    for title in gold_titles:
        sents = title_to_sents.get(title) or []
        if not sents:
            continue
        out.append(
            {
                "title": title,
                "text": " ".join(sents),
                "sentences": sents,
                "supporting_sent_ids": sf_map.get(title, []),
            }
        )
    return out


def _scan_candidates(
    titles: set[str],
    *,
    exclude_texts: set[str],
    exclude_ids: set[str],
    seed: int,
) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    files: list[tuple[str, Path]] = []
    for split_name, name in (
        ("validation", "validation-00000-of-00001.parquet"),
        ("train", "train-00000-of-00002.parquet"),
        ("train", "train-00001-of-00002.parquet"),
    ):
        p = HOTPOT_CACHE / name
        if p.exists():
            files.append((split_name, p))

    candidates: list[dict[str, Any]] = []
    for split_name, path in files:
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=512):
            rows = batch.to_pydict()
            n = len(rows.get("question") or [])
            for i in range(n):
                qtext = str(rows["question"][i]).strip()
                qn = _norm_q(qtext)
                if not qn or qn in exclude_texts:
                    continue
                if any(snip in qn for snip in DEMO_SNIPPETS):
                    continue
                native_id = str(rows["id"][i]) if rows.get("id") is not None else ""
                if native_id and native_id in exclude_ids:
                    continue
                gold_titles = _extract_gold_titles(
                    rows["supporting_facts"][i]
                    if rows.get("supporting_facts") is not None
                    else None
                )
                if len(gold_titles) < 2:
                    continue
                if not all(t in titles for t in gold_titles):
                    continue
                hotpot_type = (
                    str(rows["type"][i]) if rows.get("type") is not None else ""
                )
                level = str(rows["level"][i]) if rows.get("level") is not None else ""
                context = rows["context"][i] if rows.get("context") is not None else {}
                supporting = (
                    rows["supporting_facts"][i]
                    if rows.get("supporting_facts") is not None
                    else None
                )
                if not isinstance(context, dict):
                    continue
                paragraphs = _gold_paragraphs(context, gold_titles, supporting)
                if len(paragraphs) < 2:
                    continue
                candidates.append(
                    {
                        "id": f"phaseb_hotpot_{native_id}",
                        "question": qtext,
                        "gold_answer": str(rows["answer"][i]),
                        "gold_doc_titles": gold_titles,
                        "gold_external_keys": [f"hotpotqa:{t}" for t in gold_titles],
                        "gold_paragraphs": paragraphs,
                        "question_type": _hotpot_type_to_question_type(hotpot_type),
                        "hotpot_type": hotpot_type or None,
                        "hotpot_level": level or None,
                        "requires_all_gold_docs": True,
                        "origin": "hotpot_original",
                        "split_hint": "phase_b",
                        "provenance": {
                            "dataset": "hotpotqa/hotpot_qa",
                            "config": "distractor",
                            "split": split_name,
                            "native_id": native_id,
                            "hotpot_type": hotpot_type,
                            "hotpot_level": level,
                            "license": "CC-BY-SA-4.0",
                            "title_filter": "active_neon",
                            "phase": "B",
                        },
                    }
                )
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates


def _dedupe_near(
    items: list[dict[str, Any]], *, limit: int | None = None
) -> list[dict[str, Any]]:
    """Greedy near-dup filter; stop early once ``limit`` unique items kept."""
    kept: list[dict[str, Any]] = []
    for item in items:
        if limit is not None and len(kept) >= limit:
            break
        q = str(item["question"])
        if any(_near_dup(q, str(k["question"])) for k in kept):
            continue
        kept.append(item)
    return kept


def _assign_splits(
    items: list[dict[str, Any]],
    *,
    dev_n: int,
    test_n: int,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Stratify by hotpot_type so both splits preserve type mix.

    Earlier fill-test-then-dev depleted minority types (e.g. comparison) into
    the sealed set and left development bridge-only. Instead: (1) round-robin
    a combined pool of size test_n+dev_n, then (2) within each type, allocate
    proportionally to the two splits.
    """
    rng = random.Random(seed)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_type.setdefault(str(item.get("hotpot_type") or "other"), []).append(item)
    for bucket in by_type.values():
        rng.shuffle(bucket)

    keys = sorted(by_type.keys())
    need = test_n + dev_n
    pool: list[dict[str, Any]] = []
    while len(pool) < need and any(by_type[k] for k in keys):
        for k in keys:
            if len(pool) >= need:
                break
            if by_type[k]:
                pool.append(by_type[k].pop())

    pooled: dict[str, list[dict[str, Any]]] = {}
    for item in pool:
        pooled.setdefault(str(item.get("hotpot_type") or "other"), []).append(item)

    test: list[dict[str, Any]] = []
    dev: list[dict[str, Any]] = []
    ratio = test_n / need if need else 0.0
    for k in sorted(pooled.keys()):
        bucket = pooled[k]
        n_t = int(round(len(bucket) * ratio))
        n_t = max(0, min(len(bucket), n_t))
        test.extend(bucket[:n_t])
        dev.extend(bucket[n_t:])

    # Fix rounding drift toward exact sizes without destroying type balance.
    while len(test) > test_n and test:
        dev.append(test.pop())
    while len(dev) > dev_n and dev:
        test.append(dev.pop())
    while len(test) < test_n and by_type and any(by_type[k] for k in keys):
        for k in keys:
            if len(test) >= test_n:
                break
            if by_type[k]:
                test.append(by_type[k].pop())
    while len(dev) < dev_n and by_type and any(by_type[k] for k in keys):
        for k in keys:
            if len(dev) >= dev_n:
                break
            if by_type[k]:
                dev.append(by_type[k].pop())
    test = test[:test_n]
    dev = dev[:dev_n]

    for q in test:
        q["split"] = "test"
        q["frozen"] = True
        q["role"] = "sealed_test"
    for q in dev:
        q["split"] = "dev"
        q["frozen"] = False
        q["role"] = "development"
    rng.shuffle(test)
    rng.shuffle(dev)
    return dev, test


def _robustness_pack(*, seed: int) -> list[dict[str, Any]]:
    """Synthetic robustness cases — clearly marked, not Hotpot originals."""
    truth = json.loads(SYNTHETIC_TRUTH.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    qs: list[dict[str, Any]] = []

    # Ablated unanswerable: question is answerable in corpus, but eval harness
    # must drop gold titles from the reader/retrieval context at query time.
    qs.append(
        {
            "id": "phaseb_robust_unans_ablate_jwt",
            "question": "What JWT TTL misconfiguration caused the March payment outage?",
            "gold_answer": "INSUFFICIENT",
            "gold_doc_titles": ["incident_march"],
            "gold_doc_paths": ["data/synthetic/incident_march.md"],
            "gold_external_keys": [],
            "question_type": "unanswerable",
            "expected_status": "insufficient",
            "origin": "synthetic_robustness",
            "ablate_gold_at_query": True,
            "requires_all_gold_docs": False,
            "split": "dev",
            "role": "robustness_dev",
            "frozen": False,
            "provenance": {
                "source": "phase_b_robustness",
                "kind": "unanswerable_ablated",
                "note": "Gold docs exist in corpus but MUST be excluded from query evidence.",
                "truth_seed": truth.get("seed"),
            },
        }
    )
    qs.append(
        {
            "id": "phaseb_robust_unans_ablate_airport_style",
            "question": (
                "What was the peak concurrent session count on AuthGateway "
                "during the outage?"
            ),
            "gold_answer": "INSUFFICIENT",
            "gold_doc_titles": [],
            "gold_doc_paths": [],
            "gold_external_keys": [],
            "question_type": "unanswerable",
            "expected_status": "insufficient",
            "origin": "synthetic_robustness",
            "ablate_gold_at_query": True,
            "requires_all_gold_docs": False,
            "split": "dev",
            "role": "robustness_dev",
            "frozen": False,
            "provenance": {
                "source": "phase_b_robustness",
                "kind": "unanswerable_absent_metric",
            },
        }
    )

    # Controlled contradiction (planted in synthetic corpus).
    qs.append(
        {
            "id": "phaseb_robust_contra_deploy",
            "question": (
                "When was auth-gateway deployed on 2024-03-12 according to the "
                "change log versus the incident report?"
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
            "origin": "synthetic_robustness",
            "requires_all_gold_docs": False,
            "split": "dev",
            "role": "robustness_dev",
            "frozen": False,
            "provenance": {
                "source": "phase_b_robustness",
                "kind": "contradiction_planted",
                "grounding": "08:10_vs_14:00",
            },
        }
    )

    # Similar-but-not-contradictory negative control: related systems, no conflict label.
    qs.append(
        {
            "id": "phaseb_robust_control_related_nonconflict",
            "question": (
                "Which services are mentioned in connection with the March payment "
                "disruption, without assuming they contradict each other?"
            ),
            "gold_answer": "payment and auth-related services",
            "gold_doc_titles": ["incident_march", "status_update", "change_log"],
            "gold_doc_paths": [
                "data/synthetic/incident_march.md",
                "data/synthetic/status_update.txt",
                "data/synthetic/change_log.html",
            ],
            "gold_external_keys": [],
            "question_type": "multi_doc",
            "expected_status": "answered",
            "origin": "synthetic_robustness",
            "negative_control": True,
            "requires_all_gold_docs": False,
            "split": "dev",
            "role": "robustness_dev",
            "frozen": False,
            "provenance": {
                "source": "phase_b_robustness",
                "kind": "similar_noncontradiction_control",
            },
        }
    )

    # Query-time contradiction overlay (not written to corpus): two passages
    # with conflicting dates supplied only in oracle_overlay for harness use.
    qs.append(
        {
            "id": "phaseb_robust_contra_query_overlay",
            "question": "What date did Project Nebula launch according to the provided evidence?",
            "gold_answer": "CONFLICTING",
            "gold_doc_titles": [],
            "gold_external_keys": [],
            "question_type": "contradiction",
            "expected_status": "conflicting",
            "origin": "synthetic_robustness",
            "query_only_passages": [
                {
                    "title": "Nebula Brief A",
                    "text": "Project Nebula launched on 12 January 2021 after board approval.",
                },
                {
                    "title": "Nebula Brief B",
                    "text": "Project Nebula launched on 12 March 2021 following a delayed review.",
                },
            ],
            "requires_all_gold_docs": False,
            "split": "dev",
            "role": "robustness_dev",
            "frozen": False,
            "provenance": {
                "source": "phase_b_robustness",
                "kind": "contradiction_query_overlay",
                "note": "Passages exist only in the query context; not indexed.",
            },
        }
    )
    rng.shuffle(qs)
    return qs


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--dev-n", type=int, default=150)
    parser.add_argument("--test-n", type=int, default=300)
    args = parser.parse_args()
    ensure_dirs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    exclude_texts, exclude_ids = _load_exclusions()
    print(
        f"exclusions: texts={len(exclude_texts)} native_ids={len(exclude_ids)}",
        flush=True,
    )
    print("loading ACTIVE Hotpot titles…", flush=True)
    titles, active_meta = load_active_hotpot_titles()
    print(f"active titles={len(titles)}", flush=True)

    print("scanning Hotpot for unused eligible questions…", flush=True)
    raw = _scan_candidates(
        titles, exclude_texts=exclude_texts, exclude_ids=exclude_ids, seed=args.seed
    )
    print(f"raw eligible={len(raw)}", flush=True)
    need = args.dev_n + args.test_n
    # Keep a modest oversample buffer for cross-split near-dup filtering.
    deduped = _dedupe_near(raw, limit=max(need + 80, need))
    print(f"after near-dedupe={len(deduped)} (cap={need + 80})", flush=True)

    if len(deduped) < need:
        print(
            f"WARN: only {len(deduped)} eligible after filters; "
            f"requested {need}. Using all available.",
            file=sys.stderr,
        )
    pool = deduped
    dev, test = _assign_splits(
        pool,
        dev_n=min(args.dev_n, len(pool)),
        test_n=min(args.test_n, max(0, len(pool) - 1)),
        seed=args.seed,
    )
    # Ensure no near-dup across splits.
    filtered_dev: list[dict[str, Any]] = []
    for q in dev:
        if any(_near_dup(str(q["question"]), str(t["question"])) for t in test):
            continue
        filtered_dev.append(q)
    dev = filtered_dev[: args.dev_n]

    robust = _robustness_pack(seed=args.seed + 7)
    # Attach robustness to all payload but keep sealed test pure Hotpot.
    for i, q in enumerate([*dev, *test, *robust]):
        q["index"] = i
        q.setdefault("gold_doc_paths", [])
        q.setdefault("gold_external_keys", [])

    hotpot_questions = [*dev, *test]
    type_counts: dict[str, int] = {}
    for q in hotpot_questions:
        t = str(q.get("question_type"))
        type_counts[t] = type_counts.get(t, 0) + 1

    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "benchmark_id": "phase_b_bench_v1",
        "n_dev": len(dev),
        "n_test_sealed": len(test),
        "n_robustness_dev": len(robust),
        "n_hotpot": len(hotpot_questions),
        "type_counts_hotpot": type_counts,
        "targets": {"dev": args.dev_n, "test_sealed": args.test_n},
        "targets_met": {
            "dev": len(dev) >= args.dev_n,
            "test_sealed": len(test) >= args.test_n,
        },
        "exclusions": {
            "legacy_and_heldout_texts": len(exclude_texts),
            "native_ids": len(exclude_ids),
            "demos": DEMO_SNIPPETS,
        },
        "active_meta": active_meta,
        "methodology": {
            "hotpot_labels": "native type bridge/comparison + level",
            "oracle_evidence": "gold_paragraphs from Hotpot context for gold titles",
            "sealed_test_rule": "Do not evaluate sealed test until Phase B report is reviewed",
            "heldout_v1": "excluded from this benchmark; remains separate frozen pack",
            "robustness": (
                "Separate synthetic packs; ablate_gold_at_query must drop corpus gold "
                "from reader context; query_only_passages never touch the index"
            ),
            "scoring": "Use citation-stripped EM/token F1 from Phase A metrics",
        },
        "questions": hotpot_questions,
        "robustness_questions": robust,
    }
    write_json(OUT_ALL, payload)
    write_json(
        OUT_DEV,
        {
            "split": "dev",
            "n": len(dev),
            "questions": dev,
            "robustness_questions": robust,
        },
    )
    write_json(
        OUT_TEST,
        {
            "split": "test",
            "frozen": True,
            "sealed": True,
            "n": len(test),
            "questions": test,
            "note": "SEALED — do not run answer experiments until Phase B report review.",
        },
    )
    write_json(OUT_ROBUST, {"n": len(robust), "questions": robust})

    manifest = {
        "created_at": payload["created_at"],
        "benchmark_id": "phase_b_bench_v1",
        "seed": args.seed,
        "n_dev": len(dev),
        "n_test_sealed": len(test),
        "n_robustness_dev": len(robust),
        "targets_met": payload["targets_met"],
        "file_sha256": {
            "phase_b_bench_v1.json": _sha256_file(OUT_ALL),
            "phase_b_bench_v1_dev.json": _sha256_file(OUT_DEV),
            "phase_b_bench_v1_test_sealed.json": _sha256_file(OUT_TEST),
            "phase_b_bench_v1_robustness.json": _sha256_file(OUT_ROBUST),
        },
        "dev_ids": [q["id"] for q in dev],
        "test_ids": [q["id"] for q in test],
        "robustness_ids": [q["id"] for q in robust],
    }
    write_json(MANIFEST, manifest)
    print(
        f"wrote phase_b_bench_v1 dev={len(dev)} sealed_test={len(test)} "
        f"robust={len(robust)} targets_met={payload['targets_met']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
