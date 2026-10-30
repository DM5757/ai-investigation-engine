"""Production smoke suite against the public Render demo.

Uses real Neon + Qdrant evidence. Records detailed per-case outcomes.
Does not treat HTTP 200 alone as success.

  uv run python scripts/prod_smoke_suite.py
  uv run python scripts/prod_smoke_suite.py --cases airport,colony --pause-s 5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "docs" / "evidence" / "prod_smoke_suite.json"
OUT_MD = ROOT / "docs" / "evidence" / "prod_smoke_suite.md"
DEFAULT_BASE = "https://ai-investigation-engine-scyz.onrender.com"

# Case catalogue — keep questions exact for regression A/B.
CASES: dict[str, dict[str, Any]] = {
    "airport": {
        "letter": "A/regression-B",
        "category": "factual",
        "question": (
            "What is Roanoke–Blacksburg Regional Airport, and where is it located?"
        ),
        "mode": None,
        "expect_status": ["answered", "partial"],
        "accept_degraded": ["llm_unavailable"],
        "require_answer_any": ["woodrum", "roanoke", "virginia", "roa"],
        "forbid_answer_any": [],
        "max_citations": 6,
        "prefer_citation_title_any": ["roanoke", "woodrum", "blacksburg"],
        "notes": "Concise factual answer about Woodrum Field near Roanoke, VA.",
    },
    "multi_doc_payment": {
        "letter": "B",
        "category": "multi_document",
        "question": (
            "Which system changes caused disruptions in payment processing in March, "
            "which services were affected, and which documents support this?"
        ),
        "mode": None,
        "expect_status": ["answered", "partial", "conflicting"],
        "accept_degraded": ["llm_unavailable"],
        "min_distinct_docs": 2,
        "require_answer_any": ["payment", "auth", "march", "gateway", "neon", "jwt"],
        "notes": "Requires combining synthetic incident + change-log style sources.",
    },
    "multihop_ohio_csudh": {
        "letter": "C",
        "category": "entity_relationship_multihop",
        "question": (
            "Is Ohio State University or California State University, "
            "Dominguez Hills further west?"
        ),
        "mode": None,
        "expect_status": ["answered", "partial"],
        "accept_degraded": ["llm_unavailable"],
        "require_answer_any": [
            "dominguez",
            "california state",
            "csudh",
            "west",
        ],
        "gold_titles_active": [
            "Ohio State University",
            "California State University, Dominguez Hills",
        ],
        "notes": "HotpotQA multi-hop; both gold titles verified ACTIVE in Neon.",
    },
    "unanswerable_fraudscorer": {
        "letter": "D",
        "category": "unanswerable",
        "question": "What was FraudScorer CPU usage during the incident?",
        "mode": None,
        "expect_status": ["insufficient"],
        "accept_degraded": ["llm_unavailable"],
        "forbid_confident_numeric_cpu": True,
        "notes": "Evidence intentionally absent in synthetic corpus.",
    },
    "contradiction_deploy": {
        "letter": "E",
        "category": "contradiction",
        "question": (
            "What do the documents say about auth-gateway deploy time on "
            "2024-03-12? Note any contradictions."
        ),
        "mode": None,
        "expect_status": ["conflicting", "partial", "answered"],
        "accept_degraded": ["llm_unavailable"],
        "require_answer_any": ["08:10", "14:00", "utc", "deploy", "contradict"],
        "notes": "Synthetic planted conflict: 08:10 UTC vs 14:00 UTC.",
    },
    "colony_regression": {
        "letter": "regression-A",
        "category": "insufficient_missing_entity",
        "question": (
            "Which evidence connects the investigation of the Roanoke colony "
            "disappearance to the key individuals involved, and what conclusions "
            "can be drawn from the available documents?"
        ),
        "mode": None,
        "expect_status": ["insufficient"],
        "accept_degraded": ["llm_unavailable"],
        "forbid_citation_title_any": ["airport", "woodrum", "blacksburg"],
        "forbid_answer_any": ["woodrum field", "regional airport"],
        "max_citations_if_insufficient": 0,
        "notes": "Roanoke Colony title absent from ACTIVE corpus; must abstain.",
    },
    "budget_isolation_1": {
        "letter": "F1",
        "category": "budget_isolation",
        "question": (
            "What is Roanoke–Blacksburg Regional Airport, and where is it located?"
        ),
        "mode": None,
        "expect_status": ["answered", "partial", "llm_unavailable", "insufficient"],
        "accept_degraded": ["llm_unavailable"],
        "notes": "First of two consecutive requests; budgets must reset per request.",
    },
    "budget_isolation_2": {
        "letter": "F2",
        "category": "budget_isolation",
        "question": (
            "Where are schools in the athletic association Cardinal Hayes High "
            "School is part of located?"
        ),
        "mode": None,
        "expect_status": ["answered", "partial", "llm_unavailable", "insufficient"],
        "accept_degraded": ["llm_unavailable"],
        "notes": (
            "Second consecutive request. Pass isolation if this is not "
            "immediately budget-dead solely because F1 consumed a shared budget."
        ),
    },
}


def _get(base: str, path: str, timeout: float = 180.0) -> tuple[int, Any]:
    req = urllib.request.Request(base + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, body


def _post_query(
    base: str,
    question: str,
    *,
    mode: str | None,
    timeout: float,
) -> tuple[int, Any, float]:
    payload_obj: dict[str, Any] = {"question": question}
    if mode:
        payload_obj["mode"] = mode
    payload = json.dumps(payload_obj).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/query",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            ms = (time.perf_counter() - t0) * 1000
            return resp.status, json.loads(body), ms
    except urllib.error.HTTPError as exc:
        ms = (time.perf_counter() - t0) * 1000
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed, ms
    except TimeoutError as exc:
        ms = (time.perf_counter() - t0) * 1000
        return 0, {"error": "timeout", "detail": str(exc)}, ms
    except urllib.error.URLError as exc:
        ms = (time.perf_counter() - t0) * 1000
        return 0, {"error": "url_error", "detail": str(exc)}, ms


def _lower(s: str | None) -> str:
    return (s or "").lower()


def _citation_blob(cites: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for c in cites:
        parts.append(_lower(c.get("title")))
        parts.append(_lower(c.get("quote")))
        parts.append(_lower(c.get("doc_id")))
        parts.append(_lower(c.get("label")))
    return " ".join(parts)


def _judge(case: dict[str, Any], http_status: int, body: Any, ms: float) -> dict[str, Any]:
    """Score behavioral correctness; separate honest_degraded from pass."""
    row: dict[str, Any] = {
        "id": case["id"],
        "letter": case.get("letter"),
        "category": case.get("category"),
        "question": case["question"],
        "mode": case.get("mode") or "default",
        "expected_behavior": case.get("notes"),
        "expect_status": case.get("expect_status"),
        "http_status": http_status,
        "ms": round(ms, 1),
        "timeout_or_error": False,
        "pass": False,
        "honest_degraded": False,
        "failure_reasons": [],
    }

    if not isinstance(body, dict) or body.get("error"):
        row["timeout_or_error"] = True
        row["error"] = body
        row["failure_reasons"].append("request_failed_or_timeout")
        return row

    status = body.get("status")
    answer = body.get("answer") or ""
    cites = body.get("sources") or body.get("citations") or []
    usage = body.get("usage") or {}
    preview = body.get("evidence_preview") or []
    conflicts = body.get("conflicts") or []
    abstention = body.get("abstention_reason")
    degraded = bool(body.get("degraded"))

    titles = [(c.get("title") or c.get("doc_id") or "") for c in cites]
    distinct_docs = {c.get("doc_id") for c in cites if c.get("doc_id")}

    row.update(
        {
            "answer_status": status,
            "degraded": degraded,
            "answer": answer,
            "answer_preview": answer[:500],
            "n_citations": len(cites),
            "citation_titles": titles[:12],
            "citation_doc_ids": [c.get("doc_id") for c in cites[:12]],
            "n_conflicts": len(conflicts),
            "n_evidence_preview": len(preview),
            "usage_calls": usage.get("calls"),
            "usage_prompt_tokens": usage.get("prompt_tokens"),
            "usage_completion_tokens": usage.get("completion_tokens"),
            "usage_total_tokens": usage.get("total_tokens"),
            "abstention_reason": abstention,
            "trace_stages": [
                (t.get("stage"), round(float(t.get("latency_ms") or 0), 1))
                for t in (body.get("trace") or [])[:20]
            ],
        }
    )

    if http_status != 200:
        row["failure_reasons"].append(f"http_{http_status}")
        return row

    expect = set(case.get("expect_status") or [])
    accept_deg = set(case.get("accept_degraded") or [])

    if status in accept_deg and status not in expect:
        # Honest degraded: no invented essay
        invented = bool(answer.strip()) and status == "llm_unavailable"
        if invented and len(answer.strip()) > 80:
            row["failure_reasons"].append("llm_unavailable_with_long_answer")
        else:
            row["honest_degraded"] = True
            row["failure_reasons"].append("provider_or_budget_degraded")
        return row

    if status not in expect:
        row["failure_reasons"].append(f"unexpected_status:{status}")

    ans_l = _lower(answer)
    cite_l = _citation_blob(cites)

    for needle in case.get("require_answer_any") or []:
        if needle.lower() in ans_l:
            break
    else:
        if case.get("require_answer_any") and status in ("answered", "partial", "conflicting"):
            row["failure_reasons"].append("answer_missing_required_tokens")

    for bad in case.get("forbid_answer_any") or []:
        if bad.lower() in ans_l:
            row["failure_reasons"].append(f"forbidden_answer_token:{bad}")

    for bad in case.get("forbid_citation_title_any") or []:
        if bad.lower() in cite_l:
            row["failure_reasons"].append(f"forbidden_citation_token:{bad}")

    max_c = case.get("max_citations")
    if max_c is not None and len(cites) > max_c and status in ("answered", "partial"):
        row["failure_reasons"].append(f"too_many_citations:{len(cites)}>{max_c}")

    if status == "insufficient":
        max_ins = case.get("max_citations_if_insufficient")
        if max_ins is not None and len(cites) > max_ins:
            row["failure_reasons"].append(
                f"insufficient_but_citations:{len(cites)}>{max_ins}"
            )

    min_docs = case.get("min_distinct_docs")
    if (
        min_docs
        and status in ("answered", "partial", "conflicting")
        and len(distinct_docs) < min_docs
    ):
        row["failure_reasons"].append(
            f"too_few_distinct_docs:{len(distinct_docs)}<{min_docs}"
        )

    if case.get("forbid_confident_numeric_cpu") and status == "answered" and re.search(
        r"\b\d{1,3}\s*%|\b\d+\s*cpu\b", ans_l
    ):
        row["failure_reasons"].append("unanswerable_invented_cpu_metric")

    # Prefer relevant airport citation when answered
    prefer = case.get("prefer_citation_title_any")
    if (
        prefer
        and status in ("answered", "partial")
        and cites
        and not any(p.lower() in cite_l for p in prefer)
    ):
        row["failure_reasons"].append("citations_lack_preferred_title_tokens")

    # Conflicting case: prefer explicit conflict signal when answered fully
    if (
        case.get("category") == "contradiction"
        and status == "answered"
        and len(conflicts) == 0
        and "contradict" not in ans_l
        and "disagree" not in ans_l
    ):
        row["failure_reasons"].append("contradiction_not_surfaced")

    row["pass"] = len(row["failure_reasons"]) == 0
    return row


def _md_report(report: dict[str, Any]) -> str:
    lines = [
        "# Production smoke suite results",
        "",
        f"- Created: `{report.get('created_at')}`",
        f"- Base: `{report.get('base')}`",
        f"- Deploy: `{report.get('git_commit')}`",
        f"- Stats ACTIVE: `{report.get('active_documents')}`",
        f"- Cases pass: **{report.get('n_pass')}** / "
        f"honest_degraded: **{report.get('n_honest_degraded')}** / "
        f"fail: **{report.get('n_fail')}**",
        "",
        "| ID | Category | Status | ms | calls | cites | Verdict |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for c in report.get("cases") or []:
        verdict = (
            "PASS"
            if c.get("pass")
            else ("DEGRADED" if c.get("honest_degraded") else "FAIL")
        )
        lines.append(
            f"| `{c.get('id')}` | {c.get('category')} | "
            f"{c.get('answer_status')} | {c.get('ms')} | "
            f"{c.get('usage_calls')} | {c.get('n_citations')} | {verdict} |"
        )
    lines.append("")
    for c in report.get("cases") or []:
        lines.extend(
            [
                f"## {c.get('id')}",
                "",
                f"- Question: {c.get('question')}",
                f"- Expected: {c.get('expected_behavior')}",
                f"- Status: `{c.get('answer_status')}` degraded={c.get('degraded')}",
                f"- Duration: {c.get('ms')} ms",
                f"- Usage: calls={c.get('usage_calls')} "
                f"tokens={c.get('usage_total_tokens')}",
                f"- Citations ({c.get('n_citations')}): {c.get('citation_titles')}",
                f"- Reasons: {c.get('failure_reasons')}",
                f"- Answer preview: {c.get('answer_preview')!r}",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument(
        "--cases",
        default=",".join(CASES.keys()),
        help="Comma-separated case ids",
    )
    parser.add_argument("--pause-s", type=float, default=8.0)
    parser.add_argument("--timeout-s", type=float, default=330.0)
    parser.add_argument("--skip-wake", action="store_true")
    args = parser.parse_args()

    selected = [c.strip() for c in args.cases.split(",") if c.strip()]
    unknown = [c for c in selected if c not in CASES]
    if unknown:
        print(f"unknown cases: {unknown}", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "base": args.base,
        "timeout_s": args.timeout_s,
        "pause_s": args.pause_s,
        "steps": [],
        "cases": [],
    }

    if not args.skip_wake:
        for path in ("/api/health", "/api/health/ready", "/api/version", "/api/stats"):
            try:
                status, body = _get(args.base, path, timeout=180.0)
                report["steps"].append({"step": path, "status": status, "body": body})
                if path == "/api/version" and isinstance(body, dict):
                    report["git_commit"] = body.get("git_commit")
                if path == "/api/stats" and isinstance(body, dict):
                    report["active_documents"] = (body.get("documents_by_status") or {}).get(
                        "ACTIVE"
                    )
                print(f"wake {path}: {status}")
            except Exception as exc:  # noqa: BLE001
                report["steps"].append({"step": path, "error": str(exc)})
                OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(f"failed at {path}: {exc}")
                return 1

    prev_usage_calls: int | None = None
    for i, case_id in enumerate(selected):
        spec = dict(CASES[case_id])
        spec["id"] = case_id
        if i and args.pause_s > 0:
            time.sleep(args.pause_s)
        print(f"\n=== {case_id} ===")
        print(spec["question"][:120])
        http_status, body, ms = _post_query(
            args.base,
            spec["question"],
            mode=spec.get("mode"),
            timeout=args.timeout_s,
        )
        row = _judge(spec, http_status, body, ms)

        # Budget isolation heuristic for F2
        if case_id == "budget_isolation_2" and isinstance(body, dict):
            calls = (body.get("usage") or {}).get("calls")
            abst = _lower(body.get("abstention_reason"))
            shared_budget_death = (
                body.get("status") == "llm_unavailable"
                and "budget" in abst
                and prev_usage_calls is not None
                and prev_usage_calls >= 1
                and (calls is None or calls == 0)
            )
            if shared_budget_death:
                row["pass"] = False
                row["honest_degraded"] = False
                row["failure_reasons"].append("budget_not_isolated_across_requests")
            elif body.get("status") in ("answered", "partial", "insufficient", "conflicting"):
                row["failure_reasons"] = [
                    r for r in row["failure_reasons"] if r != "provider_or_budget_degraded"
                ]
                # isolation ok even if answer quality weak — mark isolation_ok
                row["budget_isolation_ok"] = True
            else:
                row["budget_isolation_ok"] = True  # degraded independently still ok

        if case_id == "budget_isolation_1" and isinstance(body, dict):
            prev_usage_calls = (body.get("usage") or {}).get("calls")

        report["cases"].append(row)
        verdict = (
            "PASS" if row.get("pass") else ("DEGRADED" if row.get("honest_degraded") else "FAIL")
        )
        print(
            f"{case_id}: status={row.get('answer_status')} "
            f"cites={row.get('n_citations')} calls={row.get('usage_calls')} "
            f"ms={row.get('ms')} -> {verdict} reasons={row.get('failure_reasons')}"
        )
        # Persist incrementally so a mid-run abort still leaves evidence.
        OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    n_pass = sum(1 for c in report["cases"] if c.get("pass"))
    n_deg = sum(1 for c in report["cases"] if c.get("honest_degraded") and not c.get("pass"))
    n_fail = sum(
        1
        for c in report["cases"]
        if not c.get("pass") and not c.get("honest_degraded")
    )
    report["n_pass"] = n_pass
    report["n_honest_degraded"] = n_deg
    report["n_fail"] = n_fail
    report["ok"] = n_fail == 0
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    OUT_MD.write_text(_md_report(report), encoding="utf-8")
    print(f"\nwrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print(f"pass={n_pass} degraded={n_deg} fail={n_fail}")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
