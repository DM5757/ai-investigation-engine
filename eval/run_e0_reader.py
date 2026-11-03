"""Phase B E0 experiments: oracle / raw-retrieval / legacy / LLM-baseline readers.

Development-only by default. Never touches the sealed test split unless
``--allow-sealed-test`` is explicitly passed (forbidden in Phase B stop criteria).

Usage (pilot):
  uv run python eval/run_e0_reader.py --configs e0_oracle,e0_raw,e0_legacy,e0_llm_baseline \\
      --limit 12 --pause-s 2 --run-id e0_pilot_v1

Full development:
  uv run python eval/run_e0_reader.py --configs e0_oracle,e0_raw,e0_legacy,e0_llm_baseline \\
      --run-id e0_dev_v1 --pause-s 1.5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.metrics import (  # noqa: E402
    all_gold_at_k,
    citation_accuracy,
    exact_match,
    mean,
    mrr,
    recall_at_k,
    token_f1,
)
from scripts._phase6_common import ensure_dirs, neon_doc_counts, write_json  # noqa: E402

DEV_PATH = ROOT / "eval" / "questions" / "phase_b_bench_v1_dev.json"
SEALED_PATH = ROOT / "eval" / "questions" / "phase_b_bench_v1_test_sealed.json"
RESULTS_DIR = ROOT / "eval" / "results"
CACHE_DIR = ROOT / "data" / "cache" / "e0_reader"
CHECKPOINT_DIR = ROOT / "data" / "checkpoints" / "e0_reader"

# Controlled experimental retrieval (better all-gold than prod rerank; documented).
E0_RETRIEVAL_MODE = "hybrid_rrf"
E0_TOP_K = 10


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _cache_key(
    *,
    config_id: str,
    question_id: str,
    question: str,
    passage_fingerprint: str,
    model: str,
    prompt_id: str,
) -> str:
    blob = "|".join(
        [config_id, question_id, question, passage_fingerprint, model, prompt_id]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _passage_fingerprint(passages: list[Any]) -> str:
    parts = []
    for p in passages:
        parts.append(
            f"{getattr(p, 'label', '')}:{getattr(p, 'title', '')}:{getattr(p, 'text', '')[:200]}"
        )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _read_cache(key: str) -> dict[str, Any] | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_cache(key: str, payload: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _score_answer(question: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    gold = str(question.get("gold_answer") or "")
    pred = str(result.get("answer_text") or "")
    qtype = str(question.get("question_type") or "")
    special = gold in ("INSUFFICIENT", "CONFLICTING") or qtype in (
        "unanswerable",
        "contradiction",
    )
    scores: dict[str, Any] = {
        "exact_match": 0.0 if special else exact_match(pred, gold),
        "token_f1": 0.0 if special else token_f1(pred, gold),
    }
    status = result.get("status")
    if qtype == "unanswerable" or question.get("ablate_gold_at_query"):
        scores["correct_abstention"] = 1.0 if status == "insufficient" else 0.0
        scores["false_answer_on_unanswerable"] = (
            0.0 if status == "insufficient" else 1.0
        )
    if qtype == "contradiction":
        # Structured reader reports conflicting via missing_info / status;
        # also accept explicit CONFLICTING answer text.
        ans_l = pred.strip().lower()
        miss_l = str(result.get("missing_info") or "").lower()
        detected = (
            status == "conflicting"
            or int(result.get("conflicts") or 0) > 0
            or "conflict" in ans_l
            or (status == "insufficient" and "conflict" in miss_l)
        )
        scores["contradiction_detected"] = 1.0 if detected else 0.0
    cited = [c.get("doc_id") for c in result.get("citations") or [] if c.get("doc_id")]
    # Oracle passages often lack doc_id; fall back to cited titles vs gold titles.
    gold_docs = list(result.get("gold_doc_ids") or [])
    if gold_docs and cited:
        scores["citation"] = citation_accuracy([str(x) for x in cited], gold_docs)
    else:
        gold_titles = {
            str(t).strip().lower()
            for t in (question.get("gold_doc_titles") or [])
            if t
        }
        cited_titles = {
            str(c.get("title") or "").strip().lower()
            for c in (result.get("citations") or [])
            if c.get("title")
        }
        cite_labels = {
            str(c.get("label") or "").strip().upper()
            for c in (result.get("citations") or [])
            if c.get("label")
        }
        if gold_titles and (cited_titles or cite_labels):
            # Map S-labels onto passage_titles when citation objects omit title.
            hit_titles: set[str] = set(cited_titles)
            titles_list = [
                str(t).strip().lower() for t in (result.get("passage_titles") or [])
            ]
            for c in result.get("citations") or []:
                lab = str(c.get("label") or "").strip().upper()
                m = re.match(r"S(\d+)$", lab)
                if m:
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(titles_list):
                        hit_titles.add(titles_list[idx])
            tp = len(hit_titles & gold_titles)
            prec = tp / max(1, len(hit_titles)) if hit_titles else 0.0
            rec = tp / max(1, len(gold_titles))
            f1 = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
            scores["citation"] = {
                "precision": prec,
                "recall": rec,
                "f1": f1,
                "mode": "title",
            }
            scores["multi_hop_all_gold_cited"] = (
                1.0 if gold_titles <= hit_titles else 0.0
            )
    if gold_docs and cited:
        scores["multi_hop_all_gold_cited"] = (
            1.0 if set(gold_docs) <= set(str(x) for x in cited) else 0.0
        )
    scores["answer_supported"] = 1.0 if result.get("answer_supported") else 0.0
    scores["verify_ok"] = 1.0 if result.get("verify_ok") else 0.0
    scores["invalid_citation_rate"] = float(result.get("invalid_citation_rate") or 0.0)
    return scores


def _bootstrap_ci(values: list[float], *, n_boot: int = 1000, seed: int = 0) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "low": 0.0, "high": 0.0, "n": 0}
    rng = random.Random(seed)
    means: list[float] = []
    n = len(values)
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[min(n_boot - 1, int(0.975 * n_boot))]
    return {"mean": sum(values) / n, "low": lo, "high": hi, "n": n}


def _resolve_gold_doc_ids(
    question: dict[str, Any],
    title_to: dict[str, str],
    path_to: dict[str, str],
    ext_to: dict[str, str],
) -> list[str]:
    from eval.run_eval import _resolve_gold_doc_ids as resolve

    return resolve(question, title_to, path_to, ext_to)


def _run_oracle(
    question: dict[str, Any],
    llm: Any,
    *,
    shuffle: bool,
    baseline: bool,
) -> dict[str, Any]:
    from app.investigation.reader import (
        passages_from_gold_paragraphs,
        read_passages,
        read_passages_baseline,
    )

    paras = list(question.get("gold_paragraphs") or [])
    if question.get("query_only_passages"):
        paras = list(question["query_only_passages"])
    passages = passages_from_gold_paragraphs(paras)
    if shuffle:
        rng = random.Random(hash(str(question.get("id"))) & 0xFFFFFFFF)
        texts = [p.text for p in passages]
        rng.shuffle(texts)
        for p, t in zip(passages, texts, strict=True):
            p.text = t
    t0 = time.perf_counter()
    if baseline:
        out = read_passages_baseline(question=str(question["question"]), passages=passages, llm=llm)
    else:
        out = read_passages(question=str(question["question"]), passages=passages, llm=llm)
    return {
        "status": out.status,
        "answer_text": out.answer or "",
        "citations": [
            {
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "label": c.label,
                "quote": c.quote,
                "title": next(
                    (p.title for p in passages if p.label == c.label),
                    None,
                ),
            }
            for c in out.citations
        ],
        "latency_s": time.perf_counter() - t0,
        "llm_calls": out.usage.calls,
        "tokens": out.usage.total_tokens,
        "verify_ok": out.verify_ok,
        "answer_supported": out.answer_supported,
        "unsupported_reasons": out.unsupported_reasons,
        "invalid_citation_rate": (
            1.0
            if out.supporting and not any(s.quote_ok and s.label_ok for s in out.supporting)
            else (
                sum(1 for s in out.supporting if not (s.label_ok and s.quote_ok))
                / max(1, len(out.supporting))
            )
        ),
        "retrieved_doc_ids": [],
        "reader_mode": out.mode,
        "model": out.model,
        "provider": out.provider,
        "passage_titles": [p.title for p in passages],
        "shuffled_passages": shuffle,
    }


def _run_raw(
    question: dict[str, Any],
    retriever: Any,
    llm: Any,
    *,
    gold_doc_ids: list[str],
    ablate_gold: bool,
    baseline: bool,
    title_to: dict[str, str],
) -> dict[str, Any]:
    from app.investigation.reader import (
        passages_from_retrieval_hits,
        read_passages,
        read_passages_baseline,
    )

    t0 = time.perf_counter()
    hits = retriever.retrieve(
        str(question["question"]), k=E0_TOP_K, mode=E0_RETRIEVAL_MODE
    )
    if ablate_gold and gold_doc_ids:
        gold_set = set(gold_doc_ids)
        hits = [h for h in hits if h.chunk.doc_id not in gold_set]
    # Also drop by title if external ids unresolved
    if ablate_gold:
        gold_titles = {str(t).lower() for t in (question.get("gold_doc_titles") or [])}
        if gold_titles:
            hits = [
                h
                for h in hits
                if str(h.chunk.title or "").lower() not in gold_titles
            ]
    passages = passages_from_retrieval_hits(hits, max_n=E0_TOP_K)
    if question.get("query_only_passages"):
        from app.investigation.reader import passages_from_gold_paragraphs

        passages = passages_from_gold_paragraphs(list(question["query_only_passages"]))
        hits = []
    if baseline:
        out = read_passages_baseline(
            question=str(question["question"]), passages=passages, llm=llm
        )
    else:
        out = read_passages(
            question=str(question["question"]), passages=passages, llm=llm
        )
    retrieved_ids = [h.chunk.doc_id for h in hits]
    retrieval = {}
    if gold_doc_ids:
        retrieval = {
            "recall_at_k": recall_at_k(retrieved_ids, gold_doc_ids, E0_TOP_K),
            "mrr": mrr(retrieved_ids, gold_doc_ids),
            "all_gold_at_k": all_gold_at_k(retrieved_ids, gold_doc_ids, E0_TOP_K),
        }
    return {
        "status": out.status,
        "answer_text": out.answer or "",
        "citations": [
            {
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "label": c.label,
                "quote": c.quote,
                "title": next(
                    (p.title for p in passages if p.label == c.label),
                    None,
                ),
            }
            for c in out.citations
        ],
        "latency_s": time.perf_counter() - t0,
        "llm_calls": out.usage.calls,
        "tokens": out.usage.total_tokens,
        "verify_ok": out.verify_ok,
        "answer_supported": out.answer_supported,
        "unsupported_reasons": out.unsupported_reasons,
        "invalid_citation_rate": (
            sum(1 for s in out.supporting if not (s.label_ok and s.quote_ok))
            / max(1, len(out.supporting))
        ),
        "retrieved_doc_ids": retrieved_ids,
        "retrieval": retrieval,
        "reader_mode": out.mode,
        "model": out.model,
        "provider": out.provider,
        "passage_titles": [p.title for p in passages],
        "ablated_gold": ablate_gold,
    }


def _run_legacy(
    question: dict[str, Any],
    engine: Any,
    *,
    gold_doc_ids: list[str],
) -> dict[str, Any]:
    from eval.run_eval import _run_investigation

    result = _run_investigation(
        engine, str(question["question"]), gold_doc_ids=gold_doc_ids
    )
    result["reader_mode"] = "legacy_investigation"
    result["answer_text"] = result.get("answer_text") or ""
    result["verify_ok"] = True
    result["answer_supported"] = result.get("status") == "answered"
    return result


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if not r.get("error") and not r.get("excluded_from_scoring")]
    attempted = len(rows)
    provider_fail = [
        r
        for r in rows
        if r.get("status") == "llm_unavailable"
        or "rate" in str(r.get("error") or "").lower()
        or "quota" in str(r.get("error") or "").lower()
    ]
    f1s = [float((r.get("answer") or {}).get("token_f1") or 0.0) for r in scored]
    ems = [float((r.get("answer") or {}).get("exact_match") or 0.0) for r in scored]
    supported = [
        float((r.get("answer") or {}).get("answer_supported") or 0.0) for r in scored
    ]
    cite_f1 = [
        float(((r.get("answer") or {}).get("citation") or {}).get("f1") or 0.0)
        for r in scored
        if (r.get("answer") or {}).get("citation") is not None
    ]
    multi_hop = [
        float((r.get("answer") or {}).get("multi_hop_all_gold_cited") or 0.0)
        for r in scored
        if "multi_hop_all_gold_cited" in (r.get("answer") or {})
    ]
    retr_all_gold = [
        float((r.get("retrieval") or {}).get("all_gold_at_k") or 0.0)
        for r in scored
        if (r.get("retrieval") or {}).get("all_gold_at_k") is not None
    ]
    abstain = [
        float((r.get("answer") or {}).get("correct_abstention") or 0.0)
        for r in scored
        if "correct_abstention" in (r.get("answer") or {})
    ]
    false_ans = [
        float((r.get("answer") or {}).get("false_answer_on_unanswerable") or 0.0)
        for r in scored
        if "false_answer_on_unanswerable" in (r.get("answer") or {})
    ]
    contra = [
        float((r.get("answer") or {}).get("contradiction_detected") or 0.0)
        for r in scored
        if "contradiction_detected" in (r.get("answer") or {})
    ]
    lat = [float(r.get("latency_s") or 0.0) for r in scored]
    lat_sorted = sorted(lat)
    p50 = lat_sorted[len(lat_sorted) // 2] if lat_sorted else 0.0
    p95 = lat_sorted[int(0.95 * (len(lat_sorted) - 1))] if lat_sorted else 0.0
    return {
        "n_attempted": attempted,
        "n_scored": len(scored),
        "n_provider_failures": len(provider_fail),
        "token_f1": mean(f1s),
        "exact_match": mean(ems),
        "token_f1_ci": _bootstrap_ci(f1s, seed=1),
        "exact_match_ci": _bootstrap_ci(ems, seed=2),
        "answer_supported_rate": mean(supported),
        "citation_f1": mean(cite_f1) if cite_f1 else None,
        "multi_hop_all_gold_cited": mean(multi_hop) if multi_hop else None,
        "retrieval_all_gold_at_k": mean(retr_all_gold) if retr_all_gold else None,
        "correct_abstention_rate": mean(abstain) if abstain else None,
        "false_answer_on_unanswerable": mean(false_ans) if false_ans else None,
        "contradiction_detection_rate": mean(contra) if contra else None,
        "mean_latency_s": mean(lat),
        "latency_p50_s": p50,
        "latency_p95_s": p95,
        "mean_llm_calls": mean([float(r.get("llm_calls") or 0.0) for r in scored]),
        "mean_tokens": mean([float(r.get("tokens") or 0.0) for r in scored]),
        "status_counts": {
            s: sum(1 for r in scored if r.get("status") == s)
            for s in sorted({str(r.get("status")) for r in scored})
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase B E0 reader experiments")
    parser.add_argument(
        "--configs",
        type=str,
        default="e0_oracle,e0_raw,e0_legacy,e0_llm_baseline",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pause-s", type=float, default=1.0)
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument("--include-robustness", action="store_true")
    parser.add_argument("--shuffle-oracle-control", action="store_true")
    parser.add_argument(
        "--allow-sealed-test",
        action="store_true",
        help="FORBIDDEN for Phase B stop report; sealed test must stay untouched.",
    )
    parser.add_argument(
        "--stop-after-llm-unavailable",
        type=int,
        default=3,
    )
    args = parser.parse_args()

    if args.allow_sealed_test:
        print(
            "ERROR: Phase B forbids sealed-test evaluation. Refusing to run.",
            file=sys.stderr,
        )
        sys.exit(2)

    ensure_dirs()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not DEV_PATH.is_file():
        print(
            f"ERROR: missing {DEV_PATH}; run scripts/build_phase_b_benchmark.py",
            file=sys.stderr,
        )
        sys.exit(1)

    payload = _load(DEV_PATH)
    questions = list(payload.get("questions") or [])
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]
    # Robustness is always appended after the Hotpot limit so ablation /
    # contradiction controls are not truncated away on pilots.
    if args.include_robustness:
        robust_path = ROOT / "eval" / "questions" / "phase_b_bench_v1_robustness.json"
        robust_qs = list(payload.get("robustness_questions") or [])
        if not robust_qs and robust_path.is_file():
            robust_qs = list(_load(robust_path).get("questions") or [])
        questions = questions + robust_qs

    from app.config import get_settings
    from app.deps import get_or_create_llm, reset_process_singletons
    from app.investigation.engine import InvestigationEngine
    from eval.run_eval import _build_doc_maps, _build_stack
    from scripts._phase6_common import open_session

    settings = get_settings()
    # Never enable experimental flag as production path during E0 legacy runs.
    object.__setattr__(settings, "experimental_passage_reader", False)
    object.__setattr__(settings, "eval_record_retention", True)
    reset_process_singletons()
    session = open_session(settings)
    title_to, path_to, ext_to = _build_doc_maps(session)
    corpus = neon_doc_counts(settings)
    store, retriever, _ = _build_stack(settings, E0_RETRIEVAL_MODE)
    llm = get_or_create_llm(settings)
    if llm is None:
        print("ERROR: no LLM configured", file=sys.stderr)
        sys.exit(1)
    engine = InvestigationEngine(
        retriever=retriever, store=store, llm=llm, settings=settings
    )
    engine.retriever.default_mode = E0_RETRIEVAL_MODE  # type: ignore[assignment]

    run_id = args.run_id or datetime.now(UTC).strftime("e0_%Y%m%dT%H%M%SZ")
    config_ids = [c.strip() for c in args.configs.split(",") if c.strip()]
    summaries: list[dict[str, Any]] = []

    model_id = getattr(settings, "groq_model", "") or getattr(settings, "gemini_model", "")

    for cfg_id in config_ids:
        ck_path = CHECKPOINT_DIR / f"{run_id}__{cfg_id}.json"
        per_q: list[dict[str, Any]] = []
        done: set[str] = set()
        if ck_path.exists():
            ck = _load(ck_path)
            per_q = list(ck.get("results") or [])
            done = {str(r["question_id"]) for r in per_q}
            print(f"resume {cfg_id}: {len(done)} done", flush=True)

        consecutive_fail = 0
        print(
            f"config={cfg_id} n={len(questions)} mode={E0_RETRIEVAL_MODE} k={E0_TOP_K}",
            flush=True,
        )
        for q in questions:
            qid = str(q["id"])
            if qid in done:
                continue
            gold_docs = _resolve_gold_doc_ids(q, title_to, path_to, ext_to)
            row: dict[str, Any] = {
                "question_id": qid,
                "question_type": q.get("question_type"),
                "hotpot_type": q.get("hotpot_type"),
                "hotpot_level": q.get("hotpot_level"),
                "origin": q.get("origin"),
                "gold_answer": q.get("gold_answer"),
                "gold_doc_ids": gold_docs,
                "gold_doc_titles": q.get("gold_doc_titles"),
            }
            try:
                if llm is not None and hasattr(llm, "budget"):
                    llm.budget.reset()
                ablate = bool(q.get("ablate_gold_at_query"))
                cache_passages_fp = "na"
                prompt_id = "reader_v1"
                if cfg_id == "e0_oracle":
                    # fingerprint gold paragraphs
                    from app.investigation.reader import passages_from_gold_paragraphs

                    passages = passages_from_gold_paragraphs(
                        list(q.get("query_only_passages") or q.get("gold_paragraphs") or [])
                    )
                    cache_passages_fp = _passage_fingerprint(passages)
                    key = _cache_key(
                        config_id=cfg_id,
                        question_id=qid,
                        question=str(q["question"]),
                        passage_fingerprint=cache_passages_fp,
                        model=model_id,
                        prompt_id=prompt_id,
                    )
                    cached = _read_cache(key)
                    if cached:
                        result = cached["result"]
                        row["cache_hit"] = True
                    else:
                        result = _run_oracle(
                            q,
                            llm,
                            shuffle=False,
                            baseline=False,
                        )
                        _write_cache(key, {"result": result, "question_id": qid})
                        row["cache_hit"] = False
                elif cfg_id == "e0_oracle_shuffle":
                    result = _run_oracle(q, llm, shuffle=True, baseline=False)
                    row["cache_hit"] = False
                elif cfg_id == "e0_raw":
                    result = _run_raw(
                        q,
                        retriever,
                        llm,
                        gold_doc_ids=gold_docs,
                        ablate_gold=ablate,
                        baseline=False,
                        title_to=title_to,
                    )
                    row["cache_hit"] = False
                elif cfg_id == "e0_llm_baseline":
                    # Same retrieved passages as e0_raw, unverified LLM answer.
                    result = _run_raw(
                        q,
                        retriever,
                        llm,
                        gold_doc_ids=gold_docs,
                        ablate_gold=ablate,
                        baseline=True,
                        title_to=title_to,
                    )
                    row["cache_hit"] = False
                elif cfg_id == "e0_legacy":
                    result = _run_legacy(q, engine, gold_doc_ids=gold_docs)
                    row["cache_hit"] = False
                else:
                    raise ValueError(f"unknown config {cfg_id}")

                result["gold_doc_ids"] = gold_docs
                row.update(result)
                row["answer"] = _score_answer(q, result)
                status = str(row.get("status") or "")
                if status == "llm_unavailable":
                    consecutive_fail += 1
                else:
                    consecutive_fail = 0
            except Exception as exc:  # noqa: BLE001
                row["error"] = str(exc)[:400]
                consecutive_fail += 1
                status = "error"

            per_q.append(row)
            write_json(
                ck_path,
                {
                    "run_id": run_id,
                    "config_id": cfg_id,
                    "results": per_q,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            print(
                f"  [{cfg_id}] {len(per_q)}/{len(questions)} {qid} "
                f"status={row.get('status') or '-'} "
                f"f1={(row.get('answer') or {}).get('token_f1')} "
                f"err={str(row.get('error') or '')[:50]}",
                flush=True,
            )
            if (
                args.stop_after_llm_unavailable > 0
                and consecutive_fail >= args.stop_after_llm_unavailable
            ):
                print(
                    f"stopping {cfg_id} after {consecutive_fail} consecutive provider failures",
                    flush=True,
                )
                break
            if args.pause_s > 0:
                time.sleep(args.pause_s)

        summary = {
            "config_id": cfg_id,
            "retrieval_mode": E0_RETRIEVAL_MODE,
            "k": E0_TOP_K,
            "summary": _aggregate(per_q),
        }
        summaries.append(summary)
        out_path = RESULTS_DIR / f"{run_id}__{cfg_id}.json"
        write_json(
            out_path,
            {
                "created_at": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "config_id": cfg_id,
                "split": "dev",
                "retrieval_mode": E0_RETRIEVAL_MODE,
                "k": E0_TOP_K,
                "corpus": corpus,
                "model_settings": {
                    "groq_model": settings.groq_model,
                    "gemini_model": settings.gemini_model,
                    "temperature": 0.0,
                    "prompt_id": "reader_v1",
                },
                "note": (
                    "Development split only. Sealed test not evaluated. "
                    "Scoring uses citation-stripped EM/F1."
                ),
                "summary": summary["summary"],
                "results": per_q,
            },
        )
        print(f"wrote {out_path.as_posix()}", flush=True)

    if args.shuffle_oracle_control and "e0_oracle" in config_ids:
        # optional already handled as config
        pass

    cmp_path = RESULTS_DIR / f"{run_id}__comparison.json"
    write_json(
        cmp_path,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "split": "dev",
            "retrieval_mode": E0_RETRIEVAL_MODE,
            "k": E0_TOP_K,
            "corpus": corpus,
            "summaries": summaries,
            "sealed_test_evaluated": False,
        },
    )
    print(f"comparison -> {cmp_path.as_posix()}", flush=True)
    for s in summaries:
        sm = s["summary"]
        print(
            f"{s['config_id']}: n={sm['n_scored']}/{sm['n_attempted']} "
            f"F1={sm['token_f1']:.3f} EM={sm['exact_match']:.3f} "
            f"supported={sm['answer_supported_rate']:.3f} "
            f"fail={sm['n_provider_failures']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
