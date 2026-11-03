"""Phase C: negative controls + hardened reader A/B on development only.

Never evaluates the sealed test split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
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
from eval.negative_controls import CONTROL_EXPECT, CONTROLS, gold_passages  # noqa: E402
from scripts._phase6_common import ensure_dirs, neon_doc_counts, write_json  # noqa: E402

DEV_PATH = ROOT / "eval" / "questions" / "phase_b_bench_v1_dev.json"
ROBUST_PATH = ROOT / "eval" / "questions" / "phase_c_robustness_v1.json"
RESULTS_DIR = ROOT / "eval" / "results"
CACHE_DIR = ROOT / "data" / "cache" / "phase_c_reader"
CHECKPOINT_DIR = ROOT / "data" / "checkpoints" / "phase_c_reader"

E0_RETRIEVAL_MODE = "hybrid_rrf"
E0_TOP_K = 10
PROMPT_ID = "reader_v2_phase_c"
VERIFY_ID = "verify_v2_mh"


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
    control_id: str = "",
    require_multi_hop: bool = False,
    verify_id: str = VERIFY_ID,
) -> str:
    blob = "|".join(
        [
            config_id,
            control_id,
            question_id,
            question,
            passage_fingerprint,
            model,
            prompt_id,
            verify_id,
            f"mh={int(require_multi_hop)}",
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _passage_fingerprint(passages: list[Any]) -> str:
    parts = [
        f"{getattr(p, 'label', '')}:{getattr(p, 'title', '')}:{getattr(p, 'text', '')}"
        for p in passages
    ]
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


def _bootstrap_ci(values: list[float], *, n_boot: int = 1000, seed: int = 0) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "low": 0.0, "high": 0.0, "n": 0}
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    return {
        "mean": sum(values) / n,
        "low": means[int(0.025 * n_boot)],
        "high": means[min(n_boot - 1, int(0.975 * n_boot))],
        "n": n,
    }


def _score(
    question: dict[str, Any],
    result: dict[str, Any],
    *,
    control_id: str | None = None,
) -> dict[str, Any]:
    gold = str(question.get("gold_answer") or "")
    pred = str(result.get("answer_text") or "")
    qtype = str(question.get("question_type") or "")
    status = str(result.get("status") or "")
    supported = bool(result.get("answer_supported"))
    expect = CONTROL_EXPECT.get(control_id or "", {})
    must_abstain = bool(expect.get("must_abstain")) or qtype in (
        "unanswerable",
        "contradiction",
    ) or gold in ("INSUFFICIENT", "CONFLICTING")

    special = must_abstain
    raw_em = 0.0 if special else exact_match(pred, gold)
    raw_f1 = 0.0 if special else token_f1(pred, gold)
    # Evidence-dependent success: do not credit unsupported answers.
    credit = bool(expect.get("credit_answer_f1", True))
    require_supported = bool(expect.get("require_supported", True)) and not special
    if require_supported and not supported or not credit:
        em = 0.0
        f1 = 0.0
    else:
        em = raw_em
        f1 = raw_f1

    scores: dict[str, Any] = {
        "exact_match": em,
        "token_f1": f1,
        "raw_exact_match": raw_em,
        "raw_token_f1": raw_f1,
        "answer_supported": 1.0 if supported else 0.0,
        "verify_ok": 1.0 if result.get("verify_ok") else 0.0,
        "evidence_chain_ok": 1.0 if result.get("evidence_chain_ok") else 0.0,
        "unsupported_answer": 1.0 if (status == "answered" and not supported) else 0.0,
    }

    if must_abstain or expect.get("must_abstain"):
        abstained = status in {"insufficient", "conflicting"}
        scores["correct_abstention"] = 1.0 if abstained else 0.0
        scores["false_answer"] = 0.0 if abstained else 1.0

    if qtype == "contradiction" or gold == "CONFLICTING":
        detected = status == "conflicting" or bool(result.get("contradiction"))
        # Abstention on contradiction without explicit conflict flag still counts
        # as safe behavior if answerable was rejected.
        if status == "insufficient" and not pred:
            detected = True
        scores["contradiction_detected"] = 1.0 if detected else 0.0
        scores["contradiction_false_resolution"] = (
            1.0 if status == "answered" and pred else 0.0
        )

    if question.get("negative_control") and qtype != "contradiction":
        # Non-conflict controls: wrongly reporting conflict is a false positive.
        scores["false_contradiction"] = (
            1.0 if status == "conflicting" or result.get("contradiction") else 0.0
        )

    cited = [c.get("doc_id") for c in result.get("citations") or [] if c.get("doc_id")]
    gold_docs = list(result.get("gold_doc_ids") or [])
    if gold_docs and cited:
        scores["citation"] = citation_accuracy([str(x) for x in cited], gold_docs)
        scores["multi_hop_all_gold_cited"] = (
            1.0 if set(gold_docs) <= {str(x) for x in cited} else 0.0
        )
    else:
        gold_titles = {
            str(t).strip().lower()
            for t in (question.get("gold_doc_titles") or [])
            if t
        }
        titles_list = [
            str(t).strip().lower() for t in (result.get("passage_titles") or [])
        ]
        hit_titles: set[str] = set()
        for c in result.get("citations") or []:
            if c.get("title"):
                hit_titles.add(str(c["title"]).strip().lower())
            lab = str(c.get("label") or "").strip().upper()
            m = __import__("re").match(r"S(\d+)$", lab)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(titles_list):
                    hit_titles.add(titles_list[idx])
        if gold_titles and hit_titles:
            tp = len(hit_titles & gold_titles)
            prec = tp / max(1, len(hit_titles))
            rec = tp / max(1, len(gold_titles))
            f1c = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
            scores["citation"] = {
                "precision": prec,
                "recall": rec,
                "f1": f1c,
                "mode": "title",
            }
            scores["multi_hop_all_gold_cited"] = (
                1.0 if gold_titles <= hit_titles else 0.0
            )
    scores["invalid_citation_rate"] = float(result.get("invalid_citation_rate") or 0.0)
    return scores


def _reader_result_from_output(out: Any, passages: list[Any], *, t0: float) -> dict[str, Any]:
    return {
        "status": out.status,
        "answer_text": out.answer or "",
        "citations": [
            {
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "label": c.label,
                "quote": c.quote,
                "title": next((p.title for p in passages if p.label == c.label), None),
            }
            for c in out.citations
        ],
        "latency_s": time.perf_counter() - t0,
        "llm_calls": out.usage.calls,
        "tokens": out.usage.total_tokens,
        "verify_ok": out.verify_ok,
        "answer_supported": out.answer_supported,
        "evidence_chain_ok": out.evidence_chain_ok,
        "contradiction": out.contradiction,
        "unsupported_reasons": out.unsupported_reasons,
        "missing_info": out.missing_info,
        "next_query": out.next_query,
        "invalid_citation_rate": (
            sum(1 for s in out.supporting if not (s.label_ok and s.quote_ok))
            / max(1, len(out.supporting))
        ),
        "reader_mode": out.mode,
        "model": out.model,
        "provider": out.provider,
        "passage_titles": [p.title for p in passages],
        "n_passages": len(passages),
    }


def _run_reader_on_passages(
    question: dict[str, Any],
    passages: list[Any],
    llm: Any,
    *,
    require_multi_hop: bool,
) -> dict[str, Any]:
    from app.investigation.reader import read_passages

    t0 = time.perf_counter()
    out = read_passages(
        question=str(question["question"]),
        passages=passages,
        llm=llm,
        require_multi_hop=require_multi_hop,
        min_hops=2,
    )
    return _reader_result_from_output(out, passages, t0=t0)


def _run_raw(
    question: dict[str, Any],
    retriever: Any,
    llm: Any,
    *,
    gold_doc_ids: list[str],
    require_multi_hop: bool,
) -> dict[str, Any]:
    from app.investigation.reader import passages_from_retrieval_hits, read_passages

    t0 = time.perf_counter()
    if question.get("query_only_passages") is not None and question.get(
        "origin", ""
    ).startswith("synthetic"):
        from app.investigation.reader import passages_from_gold_paragraphs

        passages = passages_from_gold_paragraphs(list(question.get("query_only_passages") or []))
        hits: list[Any] = []
    else:
        hits = retriever.retrieve(str(question["question"]), k=E0_TOP_K, mode=E0_RETRIEVAL_MODE)
        if question.get("ablate_gold_at_query") and gold_doc_ids:
            gold_set = set(gold_doc_ids)
            hits = [h for h in hits if h.chunk.doc_id not in gold_set]
        passages = passages_from_retrieval_hits(hits, max_n=E0_TOP_K)

    # Multi-hop when >=2 gold titles appear in retrieved context.
    gold_titles = {str(t).lower() for t in (question.get("gold_doc_titles") or [])}
    present = sum(
        1 for p in passages if str(p.title or "").lower() in gold_titles
    )
    need_mh = require_multi_hop and present >= 2

    out = read_passages(
        question=str(question["question"]),
        passages=passages,
        llm=llm,
        require_multi_hop=need_mh,
        min_hops=2,
    )
    result = _reader_result_from_output(out, passages, t0=t0)
    retrieved_ids = [h.chunk.doc_id for h in hits]
    if gold_doc_ids and retrieved_ids:
        result["retrieval"] = {
            "recall_at_k": recall_at_k(retrieved_ids, gold_doc_ids, E0_TOP_K),
            "mrr": mrr(retrieved_ids, gold_doc_ids),
            "all_gold_at_k": all_gold_at_k(retrieved_ids, gold_doc_ids, E0_TOP_K),
        }
    result["retrieved_doc_ids"] = retrieved_ids
    return result


def _run_legacy(
    question: dict[str, Any], engine: Any, *, gold_doc_ids: list[str]
) -> dict[str, Any]:
    from eval.run_eval import _run_investigation

    result = _run_investigation(engine, str(question["question"]), gold_doc_ids=gold_doc_ids)
    result["reader_mode"] = "legacy_investigation"
    result["answer_text"] = result.get("answer_text") or ""
    result["verify_ok"] = True
    result["answer_supported"] = result.get("status") == "answered"
    result["evidence_chain_ok"] = False
    return result


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if not r.get("error")]
    provider_fail = [
        r
        for r in rows
        if r.get("status") == "llm_unavailable"
        or "quota" in str(r.get("error") or "").lower()
        or "rate" in str(r.get("error") or "").lower()
    ]
    f1s = [float((r.get("answer") or {}).get("token_f1") or 0.0) for r in scored]
    ems = [float((r.get("answer") or {}).get("exact_match") or 0.0) for r in scored]
    supported = [float((r.get("answer") or {}).get("answer_supported") or 0.0) for r in scored]
    false_ans = [
        float((r.get("answer") or {}).get("false_answer") or 0.0)
        for r in scored
        if "false_answer" in (r.get("answer") or {})
    ]
    abstain = [
        float((r.get("answer") or {}).get("correct_abstention") or 0.0)
        for r in scored
        if "correct_abstention" in (r.get("answer") or {})
    ]
    contra = [
        float((r.get("answer") or {}).get("contradiction_detected") or 0.0)
        for r in scored
        if "contradiction_detected" in (r.get("answer") or {})
    ]
    false_contra = [
        float((r.get("answer") or {}).get("false_contradiction") or 0.0)
        for r in scored
        if "false_contradiction" in (r.get("answer") or {})
    ]
    multi = [
        float((r.get("answer") or {}).get("multi_hop_all_gold_cited") or 0.0)
        for r in scored
        if "multi_hop_all_gold_cited" in (r.get("answer") or {})
    ]
    cite = [
        float(((r.get("answer") or {}).get("citation") or {}).get("f1") or 0.0)
        for r in scored
        if (r.get("answer") or {}).get("citation") is not None
    ]
    lat = [float(r.get("latency_s") or 0.0) for r in scored]
    lat_s = sorted(lat)
    p50 = lat_s[len(lat_s) // 2] if lat_s else 0.0
    p95 = lat_s[int(0.95 * (len(lat_s) - 1))] if lat_s else 0.0
    return {
        "n_attempted": len(rows),
        "n_scored": len(scored),
        "n_provider_failures": len(provider_fail),
        "token_f1": mean(f1s),
        "exact_match": mean(ems),
        "token_f1_ci": _bootstrap_ci(f1s, seed=1),
        "exact_match_ci": _bootstrap_ci(ems, seed=2),
        "answer_supported_rate": mean(supported),
        "false_answer_rate": mean(false_ans) if false_ans else None,
        "correct_abstention_rate": mean(abstain) if abstain else None,
        "contradiction_detection_rate": mean(contra) if contra else None,
        "false_contradiction_rate": mean(false_contra) if false_contra else None,
        "citation_f1": mean(cite) if cite else None,
        "multi_hop_all_gold_cited": mean(multi) if multi else None,
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
    parser = argparse.ArgumentParser(description="Phase C reader validation (dev only)")
    parser.add_argument(
        "--configs",
        type=str,
        default="c_oracle,c_raw,c_legacy,c_neg_controls",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pause-s", type=float, default=1.2)
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument("--include-robustness", action="store_true")
    parser.add_argument("--stop-after-llm-unavailable", type=int, default=4)
    parser.add_argument(
        "--allow-sealed-test",
        action="store_true",
        help="FORBIDDEN in Phase C.",
    )
    args = parser.parse_args()
    if args.allow_sealed_test:
        print("ERROR: Phase C forbids sealed-test evaluation.", file=sys.stderr)
        sys.exit(2)

    ensure_dirs()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not DEV_PATH.is_file():
        print(f"ERROR: missing {DEV_PATH}", file=sys.stderr)
        sys.exit(1)

    payload = _load(DEV_PATH)
    questions = list(payload.get("questions") or [])
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]
    if args.include_robustness and ROBUST_PATH.is_file():
        questions = questions + list(_load(ROBUST_PATH).get("questions") or [])

    from app.config import get_settings
    from app.deps import get_or_create_llm, reset_process_singletons
    from app.investigation.engine import InvestigationEngine
    from eval.run_eval import _build_doc_maps, _build_stack
    from scripts._phase6_common import open_session

    settings = get_settings()
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

    from eval.run_eval import _resolve_gold_doc_ids

    run_id = args.run_id or datetime.now(UTC).strftime("phasec_%Y%m%dT%H%M%SZ")
    config_ids = [c.strip() for c in args.configs.split(",") if c.strip()]
    model_id = getattr(settings, "groq_model", "") or getattr(settings, "gemini_model", "")
    summaries: list[dict[str, Any]] = []

    for cfg_id in config_ids:
        ck_path = CHECKPOINT_DIR / f"{run_id}__{cfg_id}.json"
        per_q: list[dict[str, Any]] = []
        done: set[str] = set()
        if ck_path.exists():
            ck = _load(ck_path)
            per_q = list(ck.get("results") or [])
            done = {str(r["row_id"]) for r in per_q}
            print(f"resume {cfg_id}: {len(done)} done", flush=True)

        consecutive_fail = 0
        work_items: list[tuple[str, dict[str, Any], str | None]] = []
        if cfg_id == "c_neg_controls":
            for q in questions:
                if str(q.get("origin", "")).startswith("synthetic"):
                    continue
                for control_id in CONTROLS:
                    work_items.append((f"{q['id']}::{control_id}", q, control_id))
        else:
            for q in questions:
                work_items.append((str(q["id"]), q, None))

        print(f"config={cfg_id} n={len(work_items)}", flush=True)
        for row_id, q, control_id in work_items:
            if row_id in done:
                continue
            gold_docs = _resolve_gold_doc_ids(q, title_to, path_to, ext_to)
            row: dict[str, Any] = {
                "row_id": row_id,
                "question_id": q["id"],
                "control_id": control_id,
                "question_type": q.get("question_type"),
                "hotpot_type": q.get("hotpot_type"),
                "origin": q.get("origin"),
                "gold_answer": q.get("gold_answer"),
                "gold_doc_ids": gold_docs,
                "gold_doc_titles": q.get("gold_doc_titles"),
            }
            try:
                if llm is not None and hasattr(llm, "budget"):
                    llm.budget.reset()
                require_mh = bool(
                    len(q.get("gold_doc_titles") or q.get("gold_paragraphs") or []) >= 2
                    and not str(q.get("origin", "")).startswith("synthetic")
                )
                if control_id:
                    passages = CONTROLS[control_id](q)
                    # Force multi-hop completeness check when a hop was removed so
                    # single-hop answers cannot pass as fully supported.
                    require_mh = control_id == "missing_one_hop"
                    fp = _passage_fingerprint(passages)
                    key = _cache_key(
                        config_id=cfg_id,
                        question_id=str(q["id"]),
                        question=str(q["question"]),
                        passage_fingerprint=fp,
                        model=model_id,
                        prompt_id=PROMPT_ID,
                        control_id=control_id,
                        require_multi_hop=require_mh,
                    )
                    cached = _read_cache(key)
                    if cached:
                        result = cached["result"]
                        row["cache_hit"] = True
                    else:
                        result = _run_reader_on_passages(
                            q, passages, llm, require_multi_hop=require_mh
                        )
                        _write_cache(key, {"result": result, "row_id": row_id})
                        row["cache_hit"] = False
                elif cfg_id == "c_oracle":
                    passages = gold_passages(q)
                    if q.get("query_only_passages") is not None and not passages:
                        from app.investigation.reader import passages_from_gold_paragraphs

                        passages = passages_from_gold_paragraphs(
                            list(q.get("query_only_passages") or [])
                        )
                    fp = _passage_fingerprint(passages)
                    mh = require_mh and len(passages) >= 2
                    key = _cache_key(
                        config_id=cfg_id,
                        question_id=str(q["id"]),
                        question=str(q["question"]),
                        passage_fingerprint=fp,
                        model=model_id,
                        prompt_id=PROMPT_ID,
                        require_multi_hop=mh,
                    )
                    cached = _read_cache(key)
                    if cached:
                        result = cached["result"]
                        row["cache_hit"] = True
                    else:
                        result = _run_reader_on_passages(
                            q, passages, llm, require_multi_hop=mh
                        )
                        _write_cache(key, {"result": result, "row_id": row_id})
                        row["cache_hit"] = False
                elif cfg_id == "c_raw":
                    result = _run_raw(
                        q,
                        retriever,
                        llm,
                        gold_doc_ids=gold_docs,
                        require_multi_hop=require_mh,
                    )
                    row["cache_hit"] = False
                elif cfg_id == "c_legacy":
                    result = _run_legacy(q, engine, gold_doc_ids=gold_docs)
                    row["cache_hit"] = False
                else:
                    raise ValueError(f"unknown config {cfg_id}")

                result["gold_doc_ids"] = gold_docs
                row.update(result)
                row["answer"] = _score(q, result, control_id=control_id)
                status = str(row.get("status") or "")
                if status == "llm_unavailable" or row.get("error"):
                    consecutive_fail += 1
                else:
                    consecutive_fail = 0
            except Exception as exc:  # noqa: BLE001
                row["error"] = str(exc)[:400]
                consecutive_fail += 1

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
                f"  [{cfg_id}] {len(per_q)}/{len(work_items)} {row_id} "
                f"status={row.get('status') or '-'} "
                f"f1={(row.get('answer') or {}).get('token_f1')} "
                f"abst={(row.get('answer') or {}).get('correct_abstention')} "
                f"err={str(row.get('error') or '')[:40]}",
                flush=True,
            )
            if (
                args.stop_after_llm_unavailable > 0
                and consecutive_fail >= args.stop_after_llm_unavailable
            ):
                print(
                    f"stopping {cfg_id} after {consecutive_fail} consecutive failures",
                    flush=True,
                )
                break
            if args.pause_s > 0:
                time.sleep(args.pause_s)

        summary = {
            "config_id": cfg_id,
            "retrieval_mode": E0_RETRIEVAL_MODE,
            "k": E0_TOP_K,
            "prompt_id": PROMPT_ID,
            "summary": _aggregate(per_q),
        }
        # Per-control breakdown for negative controls
        if cfg_id == "c_neg_controls":
            by_c: dict[str, list[dict[str, Any]]] = {}
            for r in per_q:
                by_c.setdefault(str(r.get("control_id")), []).append(r)
            summary["by_control"] = {k: _aggregate(v) for k, v in by_c.items()}
        summaries.append(summary)
        out_path = RESULTS_DIR / f"{run_id}__{cfg_id}.json"
        write_json(
            out_path,
            {
                "created_at": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "config_id": cfg_id,
                "split": "dev",
                "sealed_test_evaluated": False,
                "retrieval_mode": E0_RETRIEVAL_MODE,
                "k": E0_TOP_K,
                "corpus": corpus,
                "model_settings": {
                    "groq_model": settings.groq_model,
                    "gemini_model": settings.gemini_model,
                    "temperature": 0.0,
                    "prompt_id": PROMPT_ID,
                },
                "experimental_passage_reader_default": False,
                "summary": summary["summary"],
                "by_control": summary.get("by_control"),
                "results": per_q,
            },
        )
        print(f"wrote {out_path.as_posix()}", flush=True)

    cmp_path = RESULTS_DIR / f"{run_id}__comparison.json"
    write_json(
        cmp_path,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "split": "dev",
            "sealed_test_evaluated": False,
            "summaries": summaries,
            "phase_b_baseline_ref": "eval/results/e0_dev_v1__comparison.json",
        },
    )
    print(f"comparison -> {cmp_path.as_posix()}", flush=True)
    for s in summaries:
        sm = s["summary"]
        print(
            f"{s['config_id']}: n={sm['n_scored']}/{sm['n_attempted']} "
            f"F1={sm['token_f1']:.3f} EM={sm['exact_match']:.3f} "
            f"supp={sm['answer_supported_rate']:.3f} "
            f"false={sm.get('false_answer_rate')} "
            f"multi={sm.get('multi_hop_all_gold_cited')} "
            f"fail={sm['n_provider_failures']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
