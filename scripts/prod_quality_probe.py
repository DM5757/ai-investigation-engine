"""Probe public Render deployment for post-fix Roanoke / multi-doc / contradiction cases."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "evidence" / "prod_quality_probe.json"
BASE = "https://ai-investigation-engine-scyz.onrender.com"

CASES = [
    {
        "id": "roanoke_colony",
        "question": "What happened to the Roanoke Colony, and why did it disappear?",
        "expect_status_in": ["insufficient", "llm_unavailable"],
    },
    {
        "id": "roanoke_airport",
        "question": (
            "What is Roanoke–Blacksburg Regional Airport, and where is it located?"
        ),
        "expect_status_in": ["answered", "partial", "llm_unavailable"],
    },
    {
        "id": "multi_doc_payment",
        "question": (
            "Which system changes caused disruptions in payment processing in March, "
            "which services were affected, and which documents support this?"
        ),
        "expect_status_in": [
            "answered",
            "partial",
            "insufficient",
            "conflicting",
            "llm_unavailable",
        ],
    },
    {
        "id": "contradiction_probe",
        "question": (
            "According to the synthetic contradiction documents, when was the "
            "conflicting deploy completed and what was the reported root cause?"
        ),
        "expect_status_in": [
            "conflicting",
            "partial",
            "insufficient",
            "answered",
            "llm_unavailable",
        ],
    },
]


def _get(path: str, timeout: float = 120.0) -> tuple[int, Any]:
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, body


def _post_query(question: str, timeout: float = 300.0) -> tuple[int, Any, float]:
    payload = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/query",
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


def main() -> int:
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "base": BASE,
        "steps": [],
    }
    # Wake + version
    for path in ("/api/health", "/api/health/ready", "/api/version", "/api/stats"):
        try:
            status, body = _get(path, timeout=180.0)
            report["steps"].append({"step": path, "status": status, "body": body})
        except Exception as exc:  # noqa: BLE001
            report["steps"].append({"step": path, "error": str(exc)})
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"failed at {path}: {exc}")
            return 1

    cases_out: list[dict[str, Any]] = []
    for case in CASES:
        status, body, ms = _post_query(case["question"])
        if not isinstance(body, dict):
            row = {
                "id": case["id"],
                "http_status": status,
                "ms": round(ms, 1),
                "error": body,
                "ok": False,
            }
        else:
            answer_status = body.get("status")
            cites = body.get("citations") or body.get("sources") or []
            row = {
                "id": case["id"],
                "http_status": status,
                "ms": round(ms, 1),
                "answer_status": answer_status,
                "degraded": body.get("degraded"),
                "n_citations": len(cites),
                "citation_titles": [
                    (c.get("title") or c.get("doc_id")) for c in cites[:8]
                ],
                "usage_calls": (body.get("usage") or {}).get("calls"),
                "abstention_reason": body.get("abstention_reason"),
                "answer_preview": (body.get("answer") or "")[:400],
                "expect_status_in": case["expect_status_in"],
                "ok": answer_status in case["expect_status_in"],
            }
        cases_out.append(row)
        print(
            f"{case['id']}: status={row.get('answer_status')} "
            f"cites={row.get('n_citations')} calls={row.get('usage_calls')} "
            f"ok={row.get('ok')} ms={row.get('ms')}"
        )

    report["cases"] = cases_out
    report["ok"] = all(bool(c.get("ok")) for c in cases_out)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {OUT} ok={report['ok']}")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
