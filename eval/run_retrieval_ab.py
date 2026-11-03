"""Retrieval-mode A/B on development Hotpot golds (no LLM).

Compares dense_only, hybrid_rrf, and hybrid_rerank on Recall@K, all-gold@K,
MRR, and latency. Development only — sealed split forbidden.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.metrics import all_gold_at_k, mean, mrr, recall_at_k  # noqa: E402
from scripts._phase6_common import ensure_dirs, neon_doc_counts, write_json  # noqa: E402

DEV_PATH = ROOT / "eval" / "questions" / "phase_b_bench_v1_dev.json"
RESULTS_DIR = ROOT / "eval" / "results"
MODES = ("dense_only", "hybrid_rrf", "hybrid_rerank")
TOP_K = 10


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    xs = sorted(vals)
    idx = min(len(xs) - 1, max(0, int(round((p / 100.0) * (len(xs) - 1)))))
    return xs[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval A/B (dev, no LLM)")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--k", type=int, default=TOP_K)
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument("--allow-sealed-test", action="store_true")
    args = parser.parse_args()
    if args.allow_sealed_test:
        print("ERROR: sealed test forbidden for retrieval A/B", file=sys.stderr)
        sys.exit(2)

    ensure_dirs()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = _load(DEV_PATH)
    questions = list(payload.get("questions") or [])
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]

    from app.config import get_settings
    from eval.run_eval import _build_doc_maps, _build_stack
    from scripts._phase6_common import open_session

    settings = get_settings()
    session = open_session(settings)
    title_to, path_to, ext_to = _build_doc_maps(session)
    corpus = neon_doc_counts(settings)
    # Build once; mode is passed per retrieve call.
    store, retriever, _ = _build_stack(settings, "hybrid_rrf")

    from eval.run_e0_reader import _resolve_gold_doc_ids

    run_id = args.run_id or datetime.now(UTC).strftime("retr_ab_%Y%m%dT%H%M%SZ")
    mode_rows: dict[str, list[dict[str, Any]]] = {m: [] for m in MODES}

    for i, q in enumerate(questions):
        qid = str(q["id"])
        gold = _resolve_gold_doc_ids(q, title_to, path_to, ext_to)
        if not gold:
            continue
        print(f"[{i + 1}/{len(questions)}] {qid}", flush=True)
        for mode in MODES:
            # dense_only maps to dense in HybridRetriever
            api_mode = "dense" if mode == "dense_only" else mode
            t0 = time.perf_counter()
            hits = retriever.retrieve(str(q["question"]), k=args.k, mode=api_mode)  # type: ignore[arg-type]
            lat = time.perf_counter() - t0
            ids = [h.chunk.doc_id for h in hits]
            mode_rows[mode].append(
                {
                    "question_id": qid,
                    "gold_doc_ids": gold,
                    "retrieved_doc_ids": ids,
                    "recall_at_k": recall_at_k(ids, gold, args.k),
                    "all_gold_at_k": all_gold_at_k(ids, gold, args.k),
                    "mrr": mrr(ids, gold),
                    "latency_s": lat,
                }
            )

    summaries = []
    for mode in MODES:
        rows = mode_rows[mode]
        lats = [float(r["latency_s"]) for r in rows]
        summaries.append(
            {
                "mode": mode,
                "n": len(rows),
                "recall_at_k": mean([float(r["recall_at_k"]) for r in rows]),
                "all_gold_at_k": mean([float(r["all_gold_at_k"]) for r in rows]),
                "mrr": mean([float(r["mrr"]) for r in rows]),
                "latency_p50_s": _percentile(lats, 50),
                "latency_p95_s": _percentile(lats, 95),
            }
        )

    # Prefer highest all-gold@K, then recall. When those are effectively tied
    # (±0.01), prefer lower p95 latency over raw MRR (rerank often raises MRR
    # while hurting multi-hop completeness or latency).
    def _rank_key(s: dict[str, Any]) -> tuple[float, float, float, float]:
        return (
            -float(s["all_gold_at_k"]),
            -float(s["recall_at_k"]),
            float(s["latency_p95_s"]),
            -float(s["mrr"]),
        )

    ranked = sorted(summaries, key=_rank_key)
    recommended = ranked[0]["mode"] if ranked else "hybrid_rrf"
    if len(ranked) >= 2:
        a, b = ranked[0], ranked[1]
        if (
            abs(float(a["all_gold_at_k"]) - float(b["all_gold_at_k"])) < 0.011
            and abs(float(a["recall_at_k"]) - float(b["recall_at_k"])) < 0.011
        ):
            # Explicitly prefer hybrid_rrf when quality is tied (Phase A + latency).
            modes = {s["mode"] for s in summaries}
            if "hybrid_rrf" in modes:
                recommended = "hybrid_rrf"

    out = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "k": args.k,
        "n_questions": len(questions),
        "corpus": corpus,
        "summaries": summaries,
        "recommended_mode": recommended,
        "rationale": (
            "Ranked by all-gold@K (multi-hop completeness), then recall@K, "
            "then MRR, then lower p95 latency."
        ),
        "per_mode_results": mode_rows,
        "sealed_test_evaluated": False,
    }
    path = RESULTS_DIR / f"{run_id}.json"
    write_json(path, out)
    print(json.dumps({"summaries": summaries, "recommended": recommended}, indent=2))
    print(f"wrote {path}", flush=True)


if __name__ == "__main__":
    main()
