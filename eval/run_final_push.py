"""Final engineering push — matched development comparison.

Configs:
  final_oracle_soft  — gold passages + SOFT verify (diagnostic ceiling)
  final_raw_soft     — hybrid_rrf top-k + SOFT verify + paraphrase support
  final_legacy       — production heuristic pipeline
  final_llm_baseline — LLM-over-top-k without structured verify
  final_engine_soft  — full engine path with experimental reader + bridge rounds

Sealed test is forbidden here. Use eval/run_sealed_final.py after freeze.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
CACHE_DIR = ROOT / "data" / "cache" / "final_reader"
CHECKPOINT_DIR = ROOT / "data" / "checkpoints" / "final_reader"

PROMPT_ID = "reader_v2_phase_c"
VERIFY_ID = "verify_final_v1"
RETRIEVAL_MODE = "hybrid_rrf"
TOP_K = 10
COVERAGE = 0.65
POLICY = "soft"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fp(passages: list[Any]) -> str:
    parts = [f"{p.label}:{p.title}:{p.text}" for p in passages]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _cache_key(qid: str, question: str, fp: str, model: str, cfg: str) -> str:
    blob = "|".join([cfg, qid, question, fp, model, PROMPT_ID, VERIFY_ID, POLICY])
    return hashlib.sha256(blob.encode()).hexdigest()


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


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    xs = sorted(vals)
    idx = min(len(xs) - 1, max(0, int(round((p / 100.0) * (len(xs) - 1)))))
    return xs[idx]


def _score(
    question: dict[str, Any],
    result: dict[str, Any],
    *,
    control_id: str | None = None,
) -> dict[str, Any]:
    gold = str(question.get("gold_answer") or "")
    pred = str(result.get("answer_text") or "")
    status = str(result.get("status") or "")
    supported = bool(result.get("answer_supported"))
    chain_ok = bool(result.get("evidence_chain_ok"))
    qtype = str(question.get("question_type") or "")
    expect = CONTROL_EXPECT.get(control_id or "", {})
    must_abstain = (
        bool(expect.get("must_abstain"))
        or qtype in ("unanswerable", "contradiction")
        or gold in ("INSUFFICIENT", "CONFLICTING")
    )
    raw_em = 0.0 if must_abstain else exact_match(pred, gold)
    raw_f1 = 0.0 if must_abstain else token_f1(pred, gold)
    if status == "answered" and supported and chain_ok and not must_abstain:
        em, f1 = raw_em, raw_f1
    else:
        em, f1 = 0.0, 0.0
    scores: dict[str, Any] = {
        "exact_match": em,
        "token_f1": f1,
        "raw_exact_match": raw_em,
        "raw_token_f1": raw_f1,
        "answer_supported": 1.0 if supported else 0.0,
        "evidence_chain_ok": 1.0 if chain_ok else 0.0,
        "full_answered": 1.0 if status == "answered" else 0.0,
        "partial": 1.0 if status == "partial" else 0.0,
        "unsupported_full_answer": 1.0
        if status == "answered" and not (supported and chain_ok)
        else 0.0,
    }
    if must_abstain:
        if status == "answered":
            ok = False
        elif status == "partial" and control_id == "missing_one_hop":
            ok = True
        else:
            ok = status in {"insufficient", "conflicting"}
        scores["correct_abstention"] = 1.0 if ok else 0.0
        scores["false_answer"] = 0.0 if ok else 1.0
        scores["appropriate_status"] = 1.0 if ok else 0.0
    if qtype == "contradiction" or gold == "CONFLICTING":
        scores["contradiction_detected"] = (
            1.0
            if status == "conflicting"
            or (status == "insufficient" and not pred)
            else 0.0
        )
    if question.get("negative_control") and qtype != "contradiction":
        scores["false_contradiction"] = (
            1.0 if status == "conflicting" or result.get("contradiction") else 0.0
        )

    gold_titles = {
        str(t).strip().lower() for t in (question.get("gold_doc_titles") or []) if t
    }
    titles_list = [str(t).strip().lower() for t in (result.get("passage_titles") or [])]
    hit: set[str] = set()
    for c in result.get("citations") or []:
        if c.get("title"):
            hit.add(str(c["title"]).strip().lower())
        lab = str(c.get("label") or "").strip().upper()
        m = __import__("re").match(r"S(\d+)$", lab)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(titles_list):
                hit.add(titles_list[idx])
    if gold_titles and (result.get("citations") or []):
        tp = len(hit & gold_titles)
        prec = tp / max(1, len(hit)) if hit else 0.0
        rec = tp / max(1, len(gold_titles))
        f1c = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
        scores["citation"] = {"precision": prec, "recall": rec, "f1": f1c}
        scores["multi_hop_all_gold_cited"] = 1.0 if gold_titles <= hit else 0.0
    return scores


def _from_reader(out: Any, passages: list[Any], *, t0: float) -> dict[str, Any]:
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
        "coverage": out.coverage,
        "passage_titles": [p.title for p in passages],
        "n_passages": len(passages),
        "reader_mode": out.mode,
        "raw_model": out.raw_model,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if not r.get("error")]

    def col(key: str) -> list[float]:
        out: list[float] = []
        for r in scored:
            ans = r.get("answer") or {}
            if key in ans:
                out.append(float(ans.get(key) or 0))
        return out

    f1 = [float((r.get("answer") or {}).get("token_f1") or 0) for r in scored]
    em = [float((r.get("answer") or {}).get("exact_match") or 0) for r in scored]
    raw_f1 = [float((r.get("answer") or {}).get("raw_token_f1") or 0) for r in scored]
    cite = [
        float(((r.get("answer") or {}).get("citation") or {}).get("f1") or 0)
        for r in scored
        if (r.get("answer") or {}).get("citation") is not None
    ]
    multi = col("multi_hop_all_gold_cited")
    lat = [float(r.get("latency_s") or 0) for r in scored]
    return {
        "n_attempted": len(rows),
        "n_scored": len(scored),
        "n_provider_failures": sum(
            1
            for r in rows
            if "quota" in str(r.get("error") or "").lower()
            or "rate" in str(r.get("error") or "").lower()
            or "unavailable" in str(r.get("error") or "").lower()
        ),
        "n_cache_hits": sum(1 for r in scored if r.get("cache_hit")),
        "token_f1_full_answered": mean(f1),
        "exact_match_full_answered": mean(em),
        "raw_token_f1_overlap": mean(raw_f1),
        "answer_supported_rate": mean(col("answer_supported")) if scored else 0.0,
        "full_answered_rate": mean(col("full_answered")) if scored else 0.0,
        "partial_rate": mean(col("partial")) if scored else 0.0,
        "evidence_chain_ok_rate": mean(col("evidence_chain_ok")) if scored else 0.0,
        "multi_hop_all_gold_cited": mean(multi) if multi else None,
        "citation_f1": mean(cite) if cite else None,
        "false_answer_rate": mean(col("false_answer")) if col("false_answer") else None,
        "correct_abstention_rate": (
            mean(col("correct_abstention")) if col("correct_abstention") else None
        ),
        "contradiction_detection_rate": (
            mean(col("contradiction_detected")) if col("contradiction_detected") else None
        ),
        "false_contradiction_rate": (
            mean(col("false_contradiction")) if col("false_contradiction") else None
        ),
        "unsupported_full_answer_rate": mean(
            [float((r.get("answer") or {}).get("unsupported_full_answer") or 0) for r in scored]
        )
        if scored
        else 0.0,
        "mean_latency_s": mean(lat),
        "latency_p50_s": _percentile(lat, 50),
        "latency_p95_s": _percentile(lat, 95),
        "mean_tokens": mean([float(r.get("tokens") or 0) for r in scored]),
        "mean_llm_calls": mean([float(r.get("llm_calls") or 0) for r in scored]),
        "status_counts": {
            s: sum(1 for r in scored if r.get("status") == s)
            for s in sorted({str(r.get("status")) for r in scored})
        },
        "retrieval_recall_at_k": mean(
            [
                float((r.get("retrieval") or {}).get("recall_at_k") or 0)
                for r in scored
                if r.get("retrieval")
            ]
        )
        if any(r.get("retrieval") for r in scored)
        else None,
        "retrieval_all_gold_at_k": mean(
            [
                float((r.get("retrieval") or {}).get("all_gold_at_k") or 0)
                for r in scored
                if r.get("retrieval")
            ]
        )
        if any(r.get("retrieval") for r in scored)
        else None,
    }


def _meets_acceptance(summary: dict[str, Any], *, neg: bool) -> dict[str, Any]:
    """Pre-registered C.1 criteria applied to this candidate."""
    checks: dict[str, Any] = {}
    unsup = summary.get("unsupported_full_answer_rate")
    checks["unsupported_full_le_0_02"] = (
        unsup is not None and float(unsup) <= 0.02,
        unsup,
    )
    if neg:
        fa = summary.get("false_answer_rate")
        checks["false_answer_le_0_05"] = (
            fa is not None and float(fa) <= 0.05,
            fa,
        )
        abst = summary.get("correct_abstention_rate")
        checks["appropriate_status_ge_0_95"] = (
            abst is not None and float(abst) >= 0.95,
            abst,
        )
    multi = summary.get("multi_hop_all_gold_cited")
    if multi is not None:
        checks["multi_hop_all_gold_ge_0_50"] = (float(multi) >= 0.50, multi)
    contra = summary.get("contradiction_detection_rate")
    if contra is not None:
        checks["contradiction_recall_ge_0_80"] = (float(contra) >= 0.80, contra)
    fcontra = summary.get("false_contradiction_rate")
    if fcontra is not None:
        checks["false_contradiction_le_0_20"] = (float(fcontra) <= 0.20, fcontra)
    return {
        k: {"pass": bool(v[0]), "value": v[1]} for k, v in checks.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--configs",
        default="final_oracle_soft,final_raw_soft,final_legacy,final_llm_baseline",
    )
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--pause-s", type=float, default=1.5)
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument("--include-robustness", action="store_true")
    parser.add_argument("--include-neg-controls", action="store_true")
    parser.add_argument("--neg-limit", type=int, default=8)
    parser.add_argument("--stop-after-llm-unavailable", type=int, default=4)
    parser.add_argument("--allow-sealed-test", action="store_true")
    args = parser.parse_args()
    if args.allow_sealed_test:
        print("ERROR: sealed forbidden; use run_sealed_final.py", file=sys.stderr)
        sys.exit(2)

    ensure_dirs()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    payload = _load(DEV_PATH)
    questions = list(payload.get("questions") or [])
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]
    if args.include_robustness and ROBUST_PATH.is_file():
        questions = questions + list(_load(ROBUST_PATH).get("questions") or [])
    if args.include_neg_controls:
        base = list(payload.get("questions") or [])[: max(4, args.neg_limit)]
        neg_qs: list[dict[str, Any]] = []
        for q in base:
            for cid, builder in CONTROLS.items():
                passages = builder(q)
                if cid == "remove_gold" and not passages:
                    nq = dict(q)
                    nq["id"] = f"{q['id']}__neg_{cid}"
                    nq["negative_control"] = True
                    nq["control_id"] = cid
                    nq["query_only_passages"] = []
                    nq["gold_answer"] = "INSUFFICIENT"
                    nq["question_type"] = "unanswerable"
                    neg_qs.append(nq)
                    continue
                if not passages and cid != "remove_gold":
                    continue
                nq = dict(q)
                nq["id"] = f"{q['id']}__neg_{cid}"
                nq["negative_control"] = True
                nq["control_id"] = cid
                nq["query_only_passages"] = passages if passages else []
                expect = CONTROL_EXPECT.get(cid, {})
                if expect.get("must_abstain"):
                    nq["gold_answer"] = expect.get("gold_answer") or "INSUFFICIENT"
                    nq["question_type"] = str(expect.get("question_type") or "unanswerable")
                neg_qs.append(nq)
                if len(neg_qs) >= args.neg_limit:
                    break
            if len(neg_qs) >= args.neg_limit:
                break
        questions = questions + neg_qs

    from app.config import get_settings
    from app.deps import get_or_create_llm, reset_process_singletons
    from app.investigation.engine import InvestigationEngine
    from app.investigation.verify import MultiHopPolicy
    from eval.run_e0_reader import _resolve_gold_doc_ids
    from eval.run_eval import _build_doc_maps, _build_stack, _run_investigation
    from scripts._phase6_common import open_session

    settings = get_settings()
    object.__setattr__(settings, "experimental_passage_reader", False)
    object.__setattr__(settings, "reader_multi_hop_policy", POLICY)
    object.__setattr__(settings, "reader_coverage_threshold", COVERAGE)
    object.__setattr__(settings, "reader_max_bridge_rounds", 1)
    object.__setattr__(settings, "eval_record_retention", True)
    reset_process_singletons()
    session = open_session(settings)
    title_to, path_to, ext_to = _build_doc_maps(session)
    corpus = neon_doc_counts(settings)
    store, retriever, _ = _build_stack(settings, RETRIEVAL_MODE)
    llm = get_or_create_llm(settings)
    if llm is None:
        print("ERROR: no LLM configured", file=sys.stderr)
        sys.exit(1)
    engine = InvestigationEngine(
        retriever=retriever, store=store, llm=llm, settings=settings
    )
    engine.retriever.default_mode = RETRIEVAL_MODE  # type: ignore[assignment]

    # Separate engine with experimental reader enabled for final_engine_soft.
    settings_exp = get_settings()
    object.__setattr__(settings_exp, "experimental_passage_reader", True)
    object.__setattr__(settings_exp, "reader_multi_hop_policy", POLICY)
    object.__setattr__(settings_exp, "reader_coverage_threshold", COVERAGE)
    object.__setattr__(settings_exp, "reader_max_bridge_rounds", 1)
    engine_exp = InvestigationEngine(
        retriever=retriever, store=store, llm=llm, settings=settings_exp
    )
    engine_exp.retriever.default_mode = RETRIEVAL_MODE  # type: ignore[assignment]

    run_id = args.run_id or datetime.now(UTC).strftime("final_%Y%m%dT%H%M%SZ")
    model_id = getattr(settings, "groq_model", "") or getattr(settings, "gemini_model", "")
    config_ids = [c.strip() for c in args.configs.split(",") if c.strip()]
    summaries: list[dict[str, Any]] = []

    from app.investigation.reader import (
        passages_from_gold_paragraphs,
        passages_from_retrieval_hits,
        read_passages,
        read_passages_baseline,
    )

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
            f"config={cfg_id} n={len(questions)} mode={RETRIEVAL_MODE} policy={POLICY}",
            flush=True,
        )
        for q in questions:
            qid = str(q["id"])
            if qid in done:
                continue
            gold_docs = _resolve_gold_doc_ids(q, title_to, path_to, ext_to)
            control_id = str(q.get("control_id") or "") or None
            row: dict[str, Any] = {
                "question_id": qid,
                "control_id": control_id,
                "question_type": q.get("question_type"),
                "hotpot_type": q.get("hotpot_type"),
                "origin": q.get("origin"),
                "gold_answer": q.get("gold_answer"),
                "gold_doc_ids": gold_docs,
                "gold_doc_titles": q.get("gold_doc_titles"),
                "negative_control": bool(q.get("negative_control")),
            }
            try:
                if hasattr(llm, "budget"):
                    llm.budget.reset()
                t0 = time.perf_counter()
                if cfg_id == "final_legacy":
                    result = _run_investigation(
                        engine, str(q["question"]), gold_doc_ids=gold_docs
                    )
                    result["answer_text"] = result.get("answer_text") or ""
                    result["answer_supported"] = result.get("status") == "answered"
                    result["evidence_chain_ok"] = False
                    result["cache_hit"] = False
                elif cfg_id == "final_engine_soft":
                    result = _run_investigation(
                        engine_exp, str(q["question"]), gold_doc_ids=gold_docs
                    )
                    result["answer_text"] = result.get("answer_text") or ""
                    result["answer_supported"] = result.get("status") in (
                        "answered",
                        "partial",
                    )
                    result["evidence_chain_ok"] = result.get("status") == "answered"
                    result["cache_hit"] = False
                else:
                    if q.get("query_only_passages") is not None and (
                        q.get("negative_control")
                        or str(q.get("origin") or "").startswith("synthetic")
                        or cfg_id == "final_oracle_soft"
                    ):
                        passages = passages_from_gold_paragraphs(
                            list(q.get("query_only_passages") or [])
                        )
                        hits: list[Any] = []
                    elif cfg_id == "final_oracle_soft":
                        passages = passages_from_gold_paragraphs(
                            list(
                                q.get("query_only_passages")
                                or q.get("gold_paragraphs")
                                or gold_passages(q)
                            )
                        )
                        hits = []
                    else:
                        hits = retriever.retrieve(
                            str(q["question"]), k=TOP_K, mode=RETRIEVAL_MODE  # type: ignore[arg-type]
                        )
                        passages = passages_from_retrieval_hits(hits, max_n=TOP_K)

                    fp = _fp(passages)
                    key = _cache_key(qid, str(q["question"]), fp, model_id, cfg_id)
                    cached = _read_cache(key)
                    if cached and cached.get("raw_model") is not None:
                        from app.investigation.reader import verify_reader_payload

                        out = verify_reader_payload(
                            cached["raw_model"],
                            passages,
                            require_multi_hop=len(
                                q.get("gold_doc_titles") or []
                            )
                            >= 2,
                            policy=MultiHopPolicy.SOFT,
                            coverage_threshold=COVERAGE,
                        )
                        out.raw_model = cached["raw_model"]
                        out.usage.calls = int((cached.get("usage") or {}).get("calls") or 0)
                        out.usage.total_tokens = int(
                            (cached.get("usage") or {}).get("total_tokens") or 0
                        )
                        result = _from_reader(out, passages, t0=t0)
                        result["cache_hit"] = True
                        result["latency_s"] = float(cached.get("latency_s") or 0.0)
                    else:
                        need_mh = len(q.get("gold_doc_titles") or []) >= 2
                        if cfg_id == "final_llm_baseline":
                            out = read_passages_baseline(
                                question=str(q["question"]),
                                passages=passages,
                                llm=llm,
                            )
                        else:
                            out = read_passages(
                                question=str(q["question"]),
                                passages=passages,
                                llm=llm,
                                require_multi_hop=need_mh,
                                policy=MultiHopPolicy.SOFT,
                                coverage_threshold=COVERAGE,
                            )
                        _write_cache(
                            key,
                            {
                                "question_id": qid,
                                "question": str(q["question"]),
                                "raw_model": out.raw_model,
                                "usage": {
                                    "calls": out.usage.calls,
                                    "total_tokens": out.usage.total_tokens,
                                },
                                "latency_s": time.perf_counter() - t0,
                                "passages": [
                                    {
                                        "label": p.label,
                                        "title": p.title,
                                        "text": p.text,
                                        "doc_id": p.doc_id,
                                        "chunk_id": p.chunk_id,
                                    }
                                    for p in passages
                                ],
                            },
                        )
                        result = _from_reader(out, passages, t0=t0)
                        result["cache_hit"] = False
                    if gold_docs and hits:
                        ids = [h.chunk.doc_id for h in hits]
                        result["retrieval"] = {
                            "recall_at_k": recall_at_k(ids, gold_docs, TOP_K),
                            "mrr": mrr(ids, gold_docs),
                            "all_gold_at_k": all_gold_at_k(ids, gold_docs, TOP_K),
                        }
                        result["retrieved_doc_ids"] = ids

                row.update(result)
                row["answer"] = _score(q, result, control_id=control_id)
                consecutive_fail = 0
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                row["error"] = err[:500]
                row["status"] = "error"
                print(f"  FAIL {qid}: {err[:160]}", flush=True)
                if any(
                    x in err.lower()
                    for x in ("quota", "rate", "unavailable", "429", "403")
                ):
                    consecutive_fail += 1
                    if consecutive_fail >= args.stop_after_llm_unavailable:
                        print("stopping config after repeated provider failures", flush=True)
                        per_q.append(row)
                        break
                else:
                    consecutive_fail = 0
            per_q.append(row)
            write_json(ck_path, {"results": per_q})
            if not row.get("cache_hit") and cfg_id not in (
                "final_legacy",
                "final_engine_soft",
            ):
                time.sleep(max(0.0, args.pause_s))

        summary = _aggregate(per_q)
        neg = any(r.get("negative_control") for r in per_q)
        acceptance = _meets_acceptance(summary, neg=neg)
        out = {
            "run_id": run_id,
            "config_id": cfg_id,
            "created_at": datetime.now(UTC).isoformat(),
            "retrieval_mode": RETRIEVAL_MODE,
            "policy": POLICY,
            "coverage_threshold": COVERAGE,
            "verify_id": VERIFY_ID,
            "prompt_id": PROMPT_ID,
            "corpus": corpus,
            "summary": summary,
            "acceptance": acceptance,
            "results": per_q,
            "sealed_test_evaluated": False,
        }
        path = RESULTS_DIR / f"{run_id}__{cfg_id}.json"
        write_json(path, out)
        summaries.append(
            {
                "config_id": cfg_id,
                "summary": summary,
                "acceptance": acceptance,
                "path": str(path),
            }
        )
        print(json.dumps({"config": cfg_id, "summary": summary}, indent=2), flush=True)

    comparison = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "verify_id": VERIFY_ID,
        "retrieval_mode": RETRIEVAL_MODE,
        "policy": POLICY,
        "summaries": summaries,
        "sealed_test_evaluated": False,
        "recommended": "final_raw_soft",
        "note": (
            "Select final_raw_soft if acceptance passes and full-answer F1 / "
            "supported rate dominate legacy without raising unsupported answers."
        ),
    }
    cpath = RESULTS_DIR / f"{run_id}__comparison.json"
    write_json(cpath, comparison)
    print(f"wrote {cpath}", flush=True)


if __name__ == "__main__":
    main()
