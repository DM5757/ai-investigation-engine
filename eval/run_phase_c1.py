"""Phase C.1: dual-policy (STRICT vs SOFT) verification on shared reader outputs.

Runs one LLM reader call per question, then applies both verification policies
offline so the comparison isolates verification — not retrieval or generation.
Development / robustness only; sealed test forbidden.
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

from eval.metrics import exact_match, mean, token_f1  # noqa: E402
from eval.negative_controls import CONTROL_EXPECT, CONTROLS, gold_passages  # noqa: E402
from scripts._phase6_common import ensure_dirs, write_json  # noqa: E402

DEV_PATH = ROOT / "eval" / "questions" / "phase_b_bench_v1_dev.json"
ROBUST_PATH = ROOT / "eval" / "questions" / "phase_c_robustness_v1.json"
PAIRED_PATH = ROOT / "eval" / "results" / "phase_c1_paired_b_vs_c.json"
RESULTS_DIR = ROOT / "eval" / "results"
CACHE_DIR = ROOT / "data" / "cache" / "phase_c1_reader"
CHECKPOINT_DIR = ROOT / "data" / "checkpoints" / "phase_c1_reader"
PROMPT_ID = "reader_v2_phase_c"
VERIFY_ID = "verify_c1_v1"
COVERAGE = 0.65


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fp(passages: list[Any]) -> str:
    parts = [
        f"{p.label}:{p.title}:{p.text}" for p in passages
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _cache_key(qid: str, question: str, fp: str, model: str) -> str:
    blob = "|".join([qid, question, fp, model, PROMPT_ID, VERIFY_ID])
    return hashlib.sha256(blob.encode()).hexdigest()


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
    must_abstain = bool(expect.get("must_abstain")) or qtype in (
        "unanswerable",
        "contradiction",
    ) or gold in ("INSUFFICIENT", "CONFLICTING")

    raw_em = 0.0 if must_abstain else exact_match(pred, gold)
    raw_f1 = 0.0 if must_abstain else token_f1(pred, gold)
    # Full-answer credit only for status=answered with chain OK.
    if status == "answered" and supported and chain_ok and not must_abstain:
        em, f1 = raw_em, raw_f1
    elif status == "partial" and supported and not must_abstain:
        # Partial: report raw overlap separately; do not count as full EM/F1.
        em, f1 = 0.0, 0.0
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
        # Full answered is always wrong on must-abstain controls.
        # SOFT may return partial on missing_one_hop (supported fragment only);
        # that is appropriate, not a false full answer.
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


def _apply_policy(
    data: dict[str, Any],
    passages: list[Any],
    *,
    policy: str,
    require_mh: bool,
) -> dict[str, Any]:
    from app.investigation.reader import verify_reader_payload

    out = verify_reader_payload(
        data,
        passages,
        require_multi_hop=require_mh,
        min_hops=2,
        policy=policy,  # type: ignore[arg-type]
        coverage_threshold=COVERAGE,
    )
    return {
        "status": out.status,
        "answer_text": out.answer or "",
        "citations": [
            {
                "label": c.label,
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "quote": c.quote,
                "title": next((p.title for p in passages if p.label == c.label), None),
            }
            for c in out.citations
        ],
        "verify_ok": out.verify_ok,
        "answer_supported": out.answer_supported,
        "evidence_chain_ok": out.evidence_chain_ok,
        "contradiction": out.contradiction,
        "unsupported_reasons": out.unsupported_reasons,
        "missing_info": out.missing_info,
        "next_query": out.next_query,
        "policy": out.policy,
        "coverage": out.coverage,
        "passage_titles": [p.title for p in passages],
        "n_passages": len(passages),
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if not r.get("error")]
    f1 = [float((r.get("answer") or {}).get("token_f1") or 0) for r in scored]
    em = [float((r.get("answer") or {}).get("exact_match") or 0) for r in scored]
    raw_f1 = [float((r.get("answer") or {}).get("raw_token_f1") or 0) for r in scored]
    supp = [float((r.get("answer") or {}).get("answer_supported") or 0) for r in scored]
    full = [float((r.get("answer") or {}).get("full_answered") or 0) for r in scored]
    partial = [float((r.get("answer") or {}).get("partial") or 0) for r in scored]
    chain = [float((r.get("answer") or {}).get("evidence_chain_ok") or 0) for r in scored]
    multi = [
        float((r.get("answer") or {}).get("multi_hop_all_gold_cited") or 0)
        for r in scored
        if "multi_hop_all_gold_cited" in (r.get("answer") or {})
    ]
    cite = [
        float(((r.get("answer") or {}).get("citation") or {}).get("f1") or 0)
        for r in scored
        if (r.get("answer") or {}).get("citation") is not None
    ]
    false_a = [
        float((r.get("answer") or {}).get("false_answer") or 0)
        for r in scored
        if "false_answer" in (r.get("answer") or {})
    ]
    abst = [
        float((r.get("answer") or {}).get("correct_abstention") or 0)
        for r in scored
        if "correct_abstention" in (r.get("answer") or {})
    ]
    contra = [
        float((r.get("answer") or {}).get("contradiction_detected") or 0)
        for r in scored
        if "contradiction_detected" in (r.get("answer") or {})
    ]
    fcontra = [
        float((r.get("answer") or {}).get("false_contradiction") or 0)
        for r in scored
        if "false_contradiction" in (r.get("answer") or {})
    ]
    unsup = [
        float((r.get("answer") or {}).get("unsupported_full_answer") or 0) for r in scored
    ]
    lat = [float(r.get("latency_s") or 0) for r in scored]
    lat_s = sorted(lat)
    return {
        "n_attempted": len(rows),
        "n_scored": len(scored),
        "n_provider_failures": sum(
            1
            for r in rows
            if "quota" in str(r.get("error") or "").lower()
            or "rate" in str(r.get("error") or "").lower()
        ),
        "token_f1_full_answered": mean(f1),
        "exact_match_full_answered": mean(em),
        "raw_token_f1_overlap": mean(raw_f1),
        "answer_supported_rate": mean(supp),
        "full_answered_rate": mean(full),
        "partial_rate": mean(partial),
        "evidence_chain_ok_rate": mean(chain),
        "multi_hop_all_gold_cited": mean(multi) if multi else None,
        "citation_f1": mean(cite) if cite else None,
        "false_answer_rate": mean(false_a) if false_a else None,
        "correct_abstention_rate": mean(abst) if abst else None,
        "contradiction_detection_rate": mean(contra) if contra else None,
        "false_contradiction_rate": mean(fcontra) if fcontra else None,
        "unsupported_full_answer_rate": mean(unsup),
        "mean_latency_s": mean(lat),
        "latency_p50_s": lat_s[len(lat_s) // 2] if lat_s else 0.0,
        "mean_tokens": mean([float(r.get("tokens") or 0) for r in scored]),
        "status_counts": {
            s: sum(1 for r in scored if r.get("status") == s)
            for s in sorted({str(r.get("status")) for r in scored})
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pause-s", type=float, default=1.2)
    parser.add_argument("--run-id", type=str, default="phasec1_policy_v1")
    parser.add_argument("--include-robustness", action="store_true")
    parser.add_argument("--include-neg-controls", action="store_true")
    parser.add_argument("--neg-limit", type=int, default=8)
    parser.add_argument("--stop-after-llm-unavailable", type=int, default=4)
    parser.add_argument("--allow-sealed-test", action="store_true")
    parser.add_argument(
        "--paired-oracle-only",
        action="store_true",
        help="Restrict Hotpot IDs to those in the Phase B/C paired oracle set.",
    )
    parser.add_argument(
        "--robustness-only",
        action="store_true",
        help="Skip Hotpot; run phase_c robustness pack only.",
    )
    parser.add_argument(
        "--neg-only",
        action="store_true",
        help="Skip Hotpot/robustness; run negative controls on --neg-limit Hotpot IDs.",
    )
    args = parser.parse_args()
    if args.allow_sealed_test:
        print("ERROR: sealed test forbidden", file=sys.stderr)
        sys.exit(2)

    ensure_dirs()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    questions = list(_load(DEV_PATH).get("questions") or [])
    if args.robustness_only or args.neg_only:
        questions = []
    if args.paired_oracle_only and PAIRED_PATH.is_file():
        paired = _load(PAIRED_PATH)
        # Prefer full common set: questions that appear in both e0 and phasec.
        _ = paired
        b = {
            str(r["question_id"])
            for r in _load(ROOT / "eval/results/e0_dev_v1__e0_oracle.json").get("results")
            or []
            if str(r.get("question_id", "")).startswith("phaseb_hotpot")
            and not r.get("error")
        }
        c = {
            str(r["question_id"])
            for r in _load(ROOT / "eval/results/phasec_ab_v1__c_oracle.json").get(
                "results"
            )
            or []
            if str(r.get("question_id", "")).startswith("phaseb_hotpot")
            and not r.get("error")
        }
        keep = b & c
        questions = [q for q in questions if q["id"] in keep]
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]

    work: list[tuple[str, dict[str, Any], str | None]] = [
        (str(q["id"]), q, None) for q in questions
    ]
    if args.include_robustness and ROBUST_PATH.is_file():
        for q in _load(ROBUST_PATH).get("questions") or []:
            work.append((str(q["id"]), q, None))
    if args.include_neg_controls or args.neg_only:
        neg_src = list(_load(DEV_PATH).get("questions") or [])
        neg_qs = [q for q in neg_src if str(q["id"]).startswith("phaseb_hotpot")][
            : args.neg_limit
        ]
        for q in neg_qs:
            for cid in CONTROLS:
                work.append((f"{q['id']}::{cid}", q, cid))

    from app.config import get_settings
    from app.deps import get_or_create_llm, reset_process_singletons
    from app.investigation.reader import read_passages

    settings = get_settings()
    object.__setattr__(settings, "experimental_passage_reader", False)
    reset_process_singletons()
    llm = get_or_create_llm(settings)
    if llm is None:
        print("ERROR: no LLM", file=sys.stderr)
        sys.exit(1)
    model_id = getattr(settings, "groq_model", "") or getattr(settings, "gemini_model", "")

    run_id = args.run_id
    per_policy: dict[str, list[dict[str, Any]]] = {"strict": [], "soft": []}
    ck = CHECKPOINT_DIR / f"{run_id}__raw_calls.json"
    raw_done: dict[str, dict[str, Any]] = {}
    if ck.exists():
        raw_done = {
            str(r["row_id"]): r for r in (_load(ck).get("raw_calls") or [])
        }
        print(f"resume raw calls: {len(raw_done)}", flush=True)

    consecutive_fail = 0
    raw_calls: list[dict[str, Any]] = list(raw_done.values())
    print(f"work items={len(work)}", flush=True)

    for row_id, q, control_id in work:
        if row_id in raw_done and raw_done[row_id].get("raw_model") is not None:
            raw_entry = raw_done[row_id]
        else:
            if control_id:
                passages = CONTROLS[control_id](q)
                require_mh = control_id == "missing_one_hop"
            else:
                passages = gold_passages(q)
                if q.get("query_only_passages") is not None:
                    from app.investigation.reader import passages_from_gold_paragraphs

                    passages = passages_from_gold_paragraphs(
                        list(q.get("query_only_passages") or [])
                    )
                require_mh = (
                    len(q.get("gold_doc_titles") or q.get("gold_paragraphs") or []) >= 2
                    and not str(q.get("origin", "")).startswith("synthetic")
                    and len(passages) >= 2
                )
            # Synthetic robustness with query_only: multi-hop if >=2 passages
            if str(q.get("id", "")).startswith("phasec_") and len(passages) >= 2:
                if q.get("question_type") not in {"unanswerable", "contradiction"}:
                    require_mh = len(passages) >= 2 and q.get("question_type") != "factual"
                # factual single-doc injection: no mh
                if q.get("provenance", {}).get("kind") == "injection":
                    require_mh = False
                if q.get("question_type") == "contradiction":
                    require_mh = False

            fp = _fp(passages)
            key = _cache_key(str(q["id"]), str(q["question"]), fp, model_id)
            cache_path = CACHE_DIR / f"{key}.json"
            t0 = time.perf_counter()
            try:
                if llm is not None and hasattr(llm, "budget"):
                    llm.budget.reset()
                if cache_path.is_file():
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
                    raw_model = cached["raw_model"]
                    usage = cached.get("usage") or {}
                    latency = float(cached.get("latency_s") or 0)
                    if cached.get("passages"):
                        from app.investigation.reader import ReaderPassage as RP

                        passages = [
                            RP(label=p["label"], title=p["title"], text=p["text"])
                            for p in cached["passages"]
                        ]
                    cache_hit = True
                    err = None
                elif not passages and control_id == "remove_gold":
                    raw_model = {
                        "answer": None,
                        "answerable": False,
                        "supporting": [],
                        "missing_info": "No passages provided.",
                        "next_query": None,
                        "conflict_kind": "none",
                    }
                    usage = {"calls": 0, "total_tokens": 0}
                    latency = 0.0
                    cache_hit = False
                    err = None
                else:
                    out = read_passages(
                        question=str(q["question"]),
                        passages=passages,
                        llm=llm,
                        require_multi_hop=False,  # isolate: apply mh in offline verify
                        policy="strict",
                        coverage_threshold=COVERAGE,
                    )
                    raw_model = out.raw_model or {}
                    usage = {
                        "calls": out.usage.calls,
                        "total_tokens": out.usage.total_tokens,
                    }
                    latency = time.perf_counter() - t0
                    cache_hit = False
                    err = None
                    cache_path.write_text(
                        json.dumps(
                            {
                                "raw_model": raw_model,
                                "usage": usage,
                                "latency_s": latency,
                                "passages": [
                                    {
                                        "label": p.label,
                                        "title": p.title,
                                        "text": p.text,
                                    }
                                    for p in passages
                                ],
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                consecutive_fail = 0 if err is None else consecutive_fail + 1
            except Exception as exc:  # noqa: BLE001
                raw_entry = {
                    "row_id": row_id,
                    "question_id": q["id"],
                    "control_id": control_id,
                    "error": str(exc)[:400],
                    "raw_model": None,
                    "passages": [],
                    "require_mh": False,
                }
                raw_calls.append(raw_entry)
                raw_done[row_id] = raw_entry
                write_json(ck, {"raw_calls": list(raw_done.values())})
                consecutive_fail += 1
                print(f"  fail {row_id}: {exc!s:.80}", flush=True)
                if consecutive_fail >= args.stop_after_llm_unavailable:
                    print("stopping after consecutive provider failures", flush=True)
                    break
                if args.pause_s > 0:
                    time.sleep(args.pause_s)
                continue

            raw_entry = {
                "row_id": row_id,
                "question_id": q["id"],
                "control_id": control_id,
                "question": q,
                "raw_model": raw_model,
                "passages": [
                    {"label": p.label, "title": p.title, "text": p.text}
                    for p in passages
                ],
                "require_mh": require_mh,
                "usage": usage,
                "latency_s": latency,
                "cache_hit": cache_hit,
                "error": err,
            }
            raw_calls.append(raw_entry)
            raw_done[row_id] = raw_entry
            write_json(ck, {"raw_calls": list(raw_done.values())})
            print(
                f"  raw {len(raw_done)}/{len(work)} {row_id} "
                f"cache={cache_hit} tok={usage.get('total_tokens')}",
                flush=True,
            )
            if args.pause_s > 0 and not cache_hit:
                time.sleep(args.pause_s)

        if raw_entry.get("error") or raw_entry.get("raw_model") is None:
            for pol in ("strict", "soft"):
                per_policy[pol].append(
                    {
                        "row_id": row_id,
                        "question_id": q["id"],
                        "control_id": control_id,
                        "error": raw_entry.get("error") or "missing_raw",
                    }
                )
            continue

        from app.investigation.reader import ReaderPassage

        passages = [
            ReaderPassage(label=p["label"], title=p["title"], text=p["text"])
            for p in raw_entry["passages"]
        ]
        require_mh = bool(raw_entry.get("require_mh"))
        for pol in ("strict", "soft"):
            result = _apply_policy(
                raw_entry["raw_model"],
                passages,
                policy=pol,
                require_mh=require_mh,
            )
            result["latency_s"] = float(raw_entry.get("latency_s") or 0)
            result["tokens"] = float((raw_entry.get("usage") or {}).get("total_tokens") or 0)
            result["llm_calls"] = float((raw_entry.get("usage") or {}).get("calls") or 0)
            row = {
                "row_id": row_id,
                "question_id": q["id"],
                "control_id": control_id,
                "gold_answer": q.get("gold_answer"),
                "gold_doc_titles": q.get("gold_doc_titles"),
                "question_type": q.get("question_type"),
                "origin": q.get("origin"),
                "negative_control": q.get("negative_control"),
                **result,
            }
            row["answer"] = _score(q, result, control_id=control_id)
            per_policy[pol].append(row)

    summaries = []
    for pol, rows in per_policy.items():
        # Prefer latest unique row_ids
        by_id: dict[str, dict[str, Any]] = {}
        for r in rows:
            by_id[str(r["row_id"])] = r
        uniq = list(by_id.values())
        sm = _aggregate(uniq)
        summaries.append({"policy": pol, "summary": sm})
        out_path = RESULTS_DIR / f"{run_id}__{pol}.json"
        write_json(
            out_path,
            {
                "created_at": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "policy": pol,
                "coverage_threshold": COVERAGE,
                "prompt_id": PROMPT_ID,
                "verify_id": VERIFY_ID,
                "sealed_test_evaluated": False,
                "experimental_passage_reader_default": False,
                "summary": sm,
                "results": uniq,
            },
        )
        print(
            f"{pol}: n={sm['n_scored']}/{sm['n_attempted']} "
            f"fullF1={sm['token_f1_full_answered']:.3f} "
            f"rawF1={sm['raw_token_f1_overlap']:.3f} "
            f"full={sm['full_answered_rate']:.3f} "
            f"partial={sm['partial_rate']:.3f} "
            f"chain={sm['evidence_chain_ok_rate']:.3f} "
            f"multi={sm.get('multi_hop_all_gold_cited')} "
            f"false={sm.get('false_answer_rate')} "
            f"unsup={sm['unsupported_full_answer_rate']:.3f}",
            flush=True,
        )
        print(f"wrote {out_path.as_posix()}", flush=True)

    cmp_path = RESULTS_DIR / f"{run_id}__comparison.json"
    write_json(
        cmp_path,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "coverage_threshold": COVERAGE,
            "summaries": summaries,
            "sealed_test_evaluated": False,
            "note": (
                "STRICT vs SOFT applied offline to the same raw_model outputs. "
                "Full EM/F1 credited only for status=answered with complete chain."
            ),
        },
    )
    print(f"comparison -> {cmp_path.as_posix()}", flush=True)


if __name__ == "__main__":
    main()
