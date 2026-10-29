"""Resumable evaluation harness.

Comparisons:
  - dense_only vs hybrid_rrf (retrieval)
  - baseline_rag vs full_investigation (answer quality; optional LLM)

Usage:
  uv run python eval/run_eval.py --configs dense_only,hybrid_rrf --split test --retrieval-only
  uv run python eval/run_eval.py --configs baseline_rag,full_investigation --split test --limit 20
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

from eval.metrics import (  # noqa: E402
    all_gold_at_k,
    citation_accuracy,
    exact_match,
    mean,
    mrr,
    multi_doc_coverage,
    recall_at_k,
    token_f1,
)
from scripts._phase6_common import ensure_dirs, neon_doc_counts, write_json  # noqa: E402

QUESTIONS_PATH = ROOT / "eval" / "questions" / "eval_set.json"
CONFIG_DIR = ROOT / "eval" / "configs"
RESULTS_DIR = ROOT / "eval" / "results"
CHECKPOINT_DIR = ROOT / "data" / "checkpoints" / "eval"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_gold_doc_ids(
    question: dict[str, Any],
    title_to_doc_id: dict[str, str],
    path_to_doc_id: dict[str, str],
    external_to_doc_id: dict[str, str],
) -> list[str]:
    ids: list[str] = []
    for key in question.get("gold_external_keys") or []:
        did = external_to_doc_id.get(str(key))
        if did:
            ids.append(did)
    for title in question.get("gold_doc_titles") or []:
        did = title_to_doc_id.get(str(title).lower())
        if did:
            ids.append(did)
    for path in question.get("gold_doc_paths") or []:
        stem = Path(str(path)).stem.lower()
        did = path_to_doc_id.get(str(path)) or title_to_doc_id.get(stem)
        if did:
            ids.append(did)
    # Preserve order, unique
    return list(dict.fromkeys(ids))


def _build_doc_maps(session: Any) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    from sqlalchemy import select

    from app.db.models import Document, DocumentStatus

    title_to: dict[str, str] = {}
    path_to: dict[str, str] = {}
    ext_to: dict[str, str] = {}
    rows = session.scalars(
        select(Document).where(Document.status == DocumentStatus.ACTIVE)
    ).all()
    for doc in rows:
        title_to[doc.title.lower()] = doc.id
        # filename stems / synthetic paths
        stem = Path(doc.filename).stem.lower()
        title_to.setdefault(stem, doc.id)
        meta = doc.doc_metadata or {}
        if isinstance(meta, dict):
            src = meta.get("source_path") or meta.get("path")
            if src:
                path_to[str(src)] = doc.id
        if doc.external_key:
            ext_to[doc.external_key] = doc.id
    return title_to, path_to, ext_to


def _build_stack(settings: Any, retrieval_mode: str) -> tuple[Any, Any, Any]:
    from app.deps import get_or_create_bm25, get_or_create_chunk_store, get_or_create_embedder
    from app.retrieval.hybrid import HybridRetriever

    store = get_or_create_chunk_store(settings)
    embedder = get_or_create_embedder(settings)
    bm25 = get_or_create_bm25(settings)
    retriever = HybridRetriever(
        store=store,
        embedder=embedder,
        bm25=bm25,
        settings=settings,
        default_mode=retrieval_mode,  # type: ignore[arg-type]
    )
    return store, retriever, embedder


def _run_retrieval(
    retriever: Any,
    question: str,
    *,
    mode: str,
    k: int,
) -> tuple[list[str], list[str], float]:
    t0 = time.perf_counter()
    hits = retriever.retrieve(question, k=k, mode=mode)
    latency = time.perf_counter() - t0
    chunk_ids = [h.chunk.chunk_id for h in hits]
    doc_ids = [h.chunk.doc_id for h in hits]
    return chunk_ids, doc_ids, latency


def _run_baseline_rag(
    retriever: Any,
    llm: Any,
    question: str,
    *,
    mode: str,
    k: int,
) -> dict[str, Any]:
    from app.investigation.aggregator import assign_source_labels
    from app.investigation.synthesizer import synthesize_answer
    from app.investigation.verifier import verify_answer_citations
    from app.schemas.evidence import Claim

    t0 = time.perf_counter()
    hits = retriever.retrieve(question, k=k, mode=mode)
    claims: list[Claim] = []
    for i, hit in enumerate(hits[:k]):
        claims.append(
            Claim(
                claim_id=f"c{i}",
                subject="evidence",
                attribute="snippet",
                value=hit.chunk.text[:200],
                quote=hit.chunk.text[:240],
                chunk_id=hit.chunk.chunk_id,
                doc_id=hit.chunk.doc_id,
                verified=True,
            )
        )
    claims = assign_source_labels(claims)
    status = "answered" if claims else "insufficient"
    text, citations, usage, _used_llm = synthesize_answer(
        question=question,
        status=status,  # type: ignore[arg-type]
        claims=claims,
        conflicts=[],
        abstention_reason=None if claims else "no retrieved evidence",
        llm=llm,
    )
    text, citations, _removed, verify_ok = verify_answer_citations(text, citations, claims)
    latency = time.perf_counter() - t0
    return {
        "status": status if verify_ok else ("partial" if status == "answered" else status),
        "answer_text": text or "",
        "citations": [
            {"doc_id": c.doc_id, "chunk_id": c.chunk_id, "label": c.label}
            for c in citations
        ],
        "verify_ok": verify_ok,
        "latency_s": latency,
        "llm_calls": usage.calls,
        "tokens": usage.total_tokens,
        "retrieved_doc_ids": [h.chunk.doc_id for h in hits],
        "retrieved_chunk_ids": [h.chunk.chunk_id for h in hits],
    }


def _run_investigation(engine: Any, question: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    ans = engine.investigate(question)
    latency = time.perf_counter() - t0
    return {
        "status": ans.status,
        "answer_text": ans.answer or "",
        "citations": [
            {"doc_id": c.doc_id, "chunk_id": c.chunk_id, "label": c.label}
            for c in ans.citations
        ],
        "conflicts": len(ans.conflicts or []),
        "latency_s": latency,
        "llm_calls": ans.usage.calls if ans.usage else 0,
        "tokens": ans.usage.total_tokens if ans.usage else 0,
        "abstention_reason": ans.abstention_reason,
        "trace_stages": [e.stage for e in (ans.trace or [])],
    }


def _score_retrieval(
    question: dict[str, Any],
    retrieved_doc_ids: list[str],
    gold_doc_ids: list[str],
    k: int,
) -> dict[str, float]:
    return {
        "recall_at_k": recall_at_k(retrieved_doc_ids, gold_doc_ids, k),
        "mrr": mrr(retrieved_doc_ids, gold_doc_ids),
        "all_gold_at_k": all_gold_at_k(retrieved_doc_ids, gold_doc_ids, k),
        "multi_doc_coverage": multi_doc_coverage(retrieved_doc_ids, gold_doc_ids, k),
    }


def _score_answer(question: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    qtype = str(question.get("question_type") or "")
    expected = question.get("expected_status")
    status = result.get("status")
    gold = str(question.get("gold_answer") or "")
    pred = str(result.get("answer_text") or "")
    scores: dict[str, Any] = {
        "exact_match": exact_match(pred, gold) if gold not in ("INSUFFICIENT", "CONFLICTING") else 0.0,
        "token_f1": token_f1(pred, gold) if gold not in ("INSUFFICIENT", "CONFLICTING") else 0.0,
    }
    if expected:
        scores["status_match"] = 1.0 if status == expected else 0.0
    if qtype == "unanswerable":
        abstained = status in ("insufficient", "partial")
        scores["correct_abstention"] = 1.0 if abstained else 0.0
        scores["false_answer_on_unanswerable"] = 0.0 if abstained else 1.0
    if qtype == "contradiction":
        scores["contradiction_detected"] = (
            1.0 if status == "conflicting" or int(result.get("conflicts") or 0) > 0 else 0.0
        )
    cited = [c.get("doc_id") for c in result.get("citations") or []]
    gold_docs = result.get("gold_doc_ids") or []
    scores["citation"] = citation_accuracy([str(x) for x in cited if x], gold_docs)
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evaluation harness")
    parser.add_argument(
        "--configs",
        type=str,
        default="dense_only,hybrid_rrf",
        help="Comma-separated config ids under eval/configs/",
    )
    parser.add_argument("--split", choices=["all", "dev", "test"], default="test")
    parser.add_argument("--limit", type=int, default=0, help="Max questions (0=all)")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--types", type=str, default="", help="Filter question_type csv")
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument("--k", type=int, default=0, help="Override top_k")
    args = parser.parse_args()

    ensure_dirs()
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if not QUESTIONS_PATH.exists():
        print("ERROR: missing eval_set.json — run scripts/build_eval_questions.py", file=sys.stderr)
        sys.exit(1)

    payload = _load_json(QUESTIONS_PATH)
    questions = list(payload["questions"])
    if args.split != "all":
        questions = [q for q in questions if q.get("split") == args.split]
    if args.types:
        allowed = {t.strip() for t in args.types.split(",") if t.strip()}
        questions = [q for q in questions if q.get("question_type") in allowed]
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]

    from app.config import get_settings
    from app.deps import get_or_create_llm, reset_process_singletons
    from app.investigation.engine import InvestigationEngine
    from scripts._phase6_common import open_session

    settings = get_settings()
    reset_process_singletons()
    session = open_session(settings)
    title_to, path_to, ext_to = _build_doc_maps(session)
    corpus_counts = neon_doc_counts(settings)

    run_id = args.run_id or datetime.now(UTC).strftime("eval_%Y%m%dT%H%M%SZ")
    config_ids = [c.strip() for c in args.configs.split(",") if c.strip()]

    all_summaries: list[dict[str, Any]] = []

    for cfg_id in config_ids:
        cfg_path = CONFIG_DIR / f"{cfg_id}.json"
        if not cfg_path.exists():
            print(f"ERROR: missing config {cfg_path}", file=sys.stderr)
            sys.exit(1)
        cfg = _load_json(cfg_path)
        mode = str(cfg.get("retrieval_mode") or "hybrid_rrf")
        pipeline = str(cfg.get("pipeline") or "retrieval_only")
        k = args.k or int(cfg.get("top_k") or 10)
        if args.retrieval_only:
            pipeline = "retrieval_only"

        ck_path = CHECKPOINT_DIR / f"{run_id}__{cfg_id}.json"
        done_ids: set[str] = set()
        per_q: list[dict[str, Any]] = []
        if ck_path.exists():
            ck = _load_json(ck_path)
            per_q = list(ck.get("results") or [])
            done_ids = {str(r["question_id"]) for r in per_q}
            print(f"resume {cfg_id}: {len(done_ids)} done", flush=True)

        store, retriever, _embedder = _build_stack(settings, mode)
        llm = None
        engine = None
        if pipeline != "retrieval_only":
            llm = get_or_create_llm(settings)
            engine = InvestigationEngine(
                retriever=retriever, store=store, llm=llm, settings=settings
            )

        print(
            f"config={cfg_id} pipeline={pipeline} mode={mode} k={k} n={len(questions)} "
            f"active_docs={corpus_counts['active_documents']}",
            flush=True,
        )

        for q in questions:
            qid = str(q["id"])
            if qid in done_ids:
                continue
            gold_docs = _resolve_gold_doc_ids(q, title_to, path_to, ext_to)
            row: dict[str, Any] = {
                "question_id": qid,
                "question_type": q.get("question_type"),
                "split": q.get("split"),
                "gold_doc_ids": gold_docs,
                "gold_doc_titles": q.get("gold_doc_titles"),
                "gold_resolved": bool(gold_docs) or q.get("question_type")
                in ("unanswerable",),
            }
            try:
                if pipeline == "retrieval_only":
                    _chunks, docs, latency = _run_retrieval(
                        retriever, str(q["question"]), mode=mode, k=k
                    )
                    row["retrieved_doc_ids"] = docs
                    row["latency_s"] = latency
                    row["retrieval"] = _score_retrieval(q, docs, gold_docs, k)
                elif pipeline == "baseline_rag":
                    result = _run_baseline_rag(
                        retriever, llm, str(q["question"]), mode=mode, k=k
                    )
                    result["gold_doc_ids"] = gold_docs
                    row.update(result)
                    row["retrieval"] = _score_retrieval(
                        q, result.get("retrieved_doc_ids") or [], gold_docs, k
                    )
                    row["answer"] = _score_answer(q, result)
                else:
                    assert engine is not None
                    # Align retriever default mode
                    engine.retriever.default_mode = mode  # type: ignore[assignment]
                    result = _run_investigation(engine, str(q["question"]))
                    result["gold_doc_ids"] = gold_docs
                    # Approximate retrieval from citations if no retrieve list
                    cited_docs = [c["doc_id"] for c in result.get("citations") or []]
                    row.update(result)
                    row["retrieval"] = _score_retrieval(q, cited_docs, gold_docs, k)
                    row["answer"] = _score_answer(q, result)
            except Exception as exc:  # noqa: BLE001
                row["error"] = str(exc)[:400]
            per_q.append(row)
            write_json(
                ck_path,
                {
                    "run_id": run_id,
                    "config": cfg,
                    "results": per_q,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            print(
                f"  [{cfg_id}] {len(per_q)}/{len(questions)} {qid} "
                f"type={q.get('question_type')} err={row.get('error', '')[:60]}",
                flush=True,
            )

        summary = _summarize(cfg, per_q, corpus_counts, k)
        out = RESULTS_DIR / f"{run_id}__{cfg_id}.json"
        write_json(out, {"summary": summary, "results": per_q})
        all_summaries.append(summary)
        print(f"wrote {out.as_posix()}", flush=True)

    session.close()
    compare_path = RESULTS_DIR / f"{run_id}__comparison.json"
    write_json(
        compare_path,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "split": args.split,
            "corpus": corpus_counts,
            "preliminary": corpus_counts["active_documents"] < 50_000,
            "summaries": all_summaries,
        },
    )
    print(f"comparison -> {compare_path.as_posix()}", flush=True)


def _summarize(
    cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    corpus_counts: dict[str, Any],
    k: int,
) -> dict[str, Any]:
    retrieval_rows = [r for r in rows if "retrieval" in r and r.get("gold_doc_ids")]
    answer_rows = [r for r in rows if "answer" in r]
    unans = [r for r in answer_rows if r.get("question_type") == "unanswerable"]
    contra = [r for r in answer_rows if r.get("question_type") == "contradiction"]
    errors = sum(1 for r in rows if r.get("error"))
    return {
        "config_id": cfg.get("id"),
        "pipeline": cfg.get("pipeline"),
        "retrieval_mode": cfg.get("retrieval_mode"),
        "k": k,
        "n_questions": len(rows),
        "n_errors": errors,
        "corpus_active_documents": corpus_counts.get("active_documents"),
        "retrieval": {
            "n": len(retrieval_rows),
            "recall_at_k": mean(r["retrieval"]["recall_at_k"] for r in retrieval_rows),
            "mrr": mean(r["retrieval"]["mrr"] for r in retrieval_rows),
            "all_gold_at_k": mean(r["retrieval"]["all_gold_at_k"] for r in retrieval_rows),
            "multi_doc_coverage": mean(
                r["retrieval"]["multi_doc_coverage"] for r in retrieval_rows
            ),
            "mean_latency_s": mean(float(r.get("latency_s") or 0.0) for r in retrieval_rows),
        },
        "answer": {
            "n": len(answer_rows),
            "exact_match": mean(float(r["answer"].get("exact_match") or 0) for r in answer_rows),
            "token_f1": mean(float(r["answer"].get("token_f1") or 0) for r in answer_rows),
            "citation_f1": mean(
                float((r["answer"].get("citation") or {}).get("f1") or 0) for r in answer_rows
            ),
            "correct_abstention_rate": mean(
                float(r["answer"].get("correct_abstention") or 0) for r in unans
            )
            if unans
            else None,
            "contradiction_detection_rate": mean(
                float(r["answer"].get("contradiction_detected") or 0) for r in contra
            )
            if contra
            else None,
            "mean_latency_s": mean(float(r.get("latency_s") or 0) for r in answer_rows),
            "mean_llm_calls": mean(float(r.get("llm_calls") or 0) for r in answer_rows),
            "mean_tokens": mean(float(r.get("tokens") or 0) for r in answer_rows),
        },
    }


if __name__ == "__main__":
    main()
