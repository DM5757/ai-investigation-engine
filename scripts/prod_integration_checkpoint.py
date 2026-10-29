"""Production integration checkpoint against live Render + cloud backends.

Loads secrets from local .env (never prints them). Hits the public Render URL for
API lifecycle checks and verifies Qdrant Cloud / Neon directly for index/DB proof.

Usage:
  uv run python scripts/prod_integration_checkpoint.py
  uv run python scripts/prod_integration_checkpoint.py --phase persist --doc-id <uuid>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

# Ensure project root on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.db.url import normalize_database_url  # noqa: E402
from app.embeddings.fastembed_provider import FastEmbedProvider  # noqa: E402
from app.index.qdrant_store import QdrantChunkStore  # noqa: E402

DEFAULT_BASE = "https://ai-investigation-engine-scyz.onrender.com"
EVIDENCE = ROOT / "docs" / "evidence" / "prod_integration_checkpoint.json"


def _secret(settings: Any, name: str) -> str:
    val = getattr(settings, name, None)
    if val is None:
        return ""
    if hasattr(val, "get_secret_value"):
        return str(val.get_secret_value() or "")
    return str(val or "")


def _redact_headers(token: str) -> dict[str, str]:
    return {"X-Admin-Token": token}


def check_qdrant(settings: Any) -> dict[str, Any]:
    url = settings.qdrant_url
    key = _secret(settings, "qdrant_api_key")
    if not url:
        return {"ok": False, "error": "QDRANT_URL missing"}
    store = QdrantChunkStore.remote(
        url,
        api_key=key or None,
        strategy=settings.chunk_strategy,
        embedding_short=settings.embedding_model_short,
        dense_size=settings.dense_vector_size,
    )
    store.ensure_collection()
    info = store.client.get_collection(store.collection)
    vectors = getattr(info.config.params, "vectors", None)
    sparse = getattr(info.config.params, "sparse_vectors", None)
    # Point count
    count = store.client.count(collection_name=store.collection, exact=True).count
    dense_ok = False
    dense_size = None
    if isinstance(vectors, dict) and "dense" in vectors:
        dense_ok = True
        dense_size = getattr(vectors["dense"], "size", None)
    sparse_ok = isinstance(sparse, dict) and "sparse" in sparse
    return {
        "ok": True,
        "collection": store.collection,
        "points_count": int(count),
        "dense_named_vector": dense_ok,
        "dense_size": dense_size,
        "sparse_named_vector": sparse_ok,
        "status": str(getattr(info, "status", "")),
    }


def check_embeddings() -> dict[str, Any]:
    provider = FastEmbedProvider(model_name="BAAI/bge-small-en-v1.5")
    q = "PaymentService disruptions after auth-gateway deploy"
    # Query uses BGE instruction prefix inside provider.
    vq = provider.embed_query(q)
    vd = provider.embed_documents([q])[0]
    # Query and passage vectors must differ because of query prefix.
    same = vq == vd
    nonzero = any(abs(x) > 1e-9 for x in vq)
    return {
        "ok": nonzero and provider.dimensions == 384 and not same,
        "model": provider.model_name,
        "dims": provider.dimensions,
        "query_nonzero": nonzero,
        "query_differs_from_passage": not same,
        "sample_norm": round(sum(x * x for x in vq) ** 0.5, 4),
    }


def check_neon(settings: Any) -> dict[str, Any]:
    url = normalize_database_url(settings.database_url)
    eng = get_engine(url)
    with eng.connect() as conn:
        one = conn.execute(text("SELECT 1")).scalar()
        db = conn.execute(text("SELECT current_database()")).scalar()
        n_docs = conn.execute(
            text("SELECT count(*) FROM documents WHERE status != 'DELETED'")
        ).scalar()
    return {
        "ok": one == 1,
        "database": db,
        "active_ish_documents": int(n_docs or 0),
        "dialect_prefix": url.split("://", 1)[0],
    }


def api_e2e(base: str, admin_token: str, *, skip_delete: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"base": base, "steps": [], "skip_delete": skip_delete}
    timeout = httpx.Timeout(180.0, connect=60.0)
    with httpx.Client(base_url=base, timeout=timeout) as client:
        t0 = time.perf_counter()
        ready = client.get("/api/health/ready")
        out["ready_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["ready"] = ready.json()
        out["steps"].append({"step": "ready", "status": ready.status_code})

        # Unauthorized upload
        files = {
            "file": (
                "prod_checkpoint.txt",
                b"Auth-gateway March 12 deploy caused PaymentService timeouts for six hours.",
                "text/plain",
            )
        }
        unauth = client.post("/api/documents", files=files)
        out["steps"].append(
            {
                "step": "upload_unauthorized",
                "status": unauth.status_code,
                "ok": unauth.status_code == 401,
            }
        )

        # Authorized upload
        t1 = time.perf_counter()
        up = client.post(
            "/api/documents",
            headers=_redact_headers(admin_token),
            data={"external_key": f"prod-checkpoint-{uuid.uuid4().hex[:8]}"},
            files=files,
        )
        upload_ms = round((time.perf_counter() - t1) * 1000, 1)
        ctype = up.headers.get("content-type", "")
        up_body = up.json() if ctype.startswith("application/json") else {}
        doc_id = up_body.get("document_id")
        out["steps"].append(
            {
                "step": "upload",
                "status": up.status_code,
                "outcome": up_body.get("outcome"),
                "document_id": doc_id,
                "latency_ms": upload_ms,
            }
        )
        if up.status_code >= 400 or not doc_id:
            out["ok"] = False
            out["error"] = "upload_failed"
            return out

        # Chunks
        chunks = client.get(f"/api/documents/{doc_id}/chunks")
        cbody = chunks.json() if chunks.status_code == 200 else {}
        n_chunks = len(cbody.get("items") or []) if isinstance(cbody, dict) else 0
        out["steps"].append(
            {
                "step": "chunks",
                "status": chunks.status_code,
                "n": n_chunks,
            }
        )

        # Query
        t2 = time.perf_counter()
        q = client.post(
            "/api/query",
            json={
                "question": "What caused PaymentService timeouts after the March deploy?",
                "mode": "hybrid_rerank",
            },
        )
        query_ms = round((time.perf_counter() - t2) * 1000, 1)
        qbody = q.json() if q.status_code == 200 else {}
        cites = qbody.get("citations") or []
        sources = qbody.get("sources") or []
        out["steps"].append(
            {
                "step": "query",
                "status": q.status_code,
                "answer_status": qbody.get("status"),
                "n_citations": len(cites),
                "n_sources": len(sources),
                "latency_ms": query_ms,
                "answer_preview": (qbody.get("answer") or "")[:240],
                "citation_doc_ids": sorted(
                    {c.get("doc_id") for c in cites if isinstance(c, dict)}
                ),
            }
        )

        # Update
        files2 = {
            "file": (
                "prod_checkpoint.txt",
                (
                    b"Auth-gateway March 12 deploy caused PaymentService "
                    b"timeouts for EIGHT hours. Revision 2."
                ),
                "text/plain",
            )
        }
        upd = client.put(
            f"/api/documents/{doc_id}",
            headers=_redact_headers(admin_token),
            files=files2,
        )
        ubody = upd.json() if upd.status_code == 200 else {}
        out["steps"].append(
            {
                "step": "update",
                "status": upd.status_code,
                "outcome": ubody.get("outcome"),
                "active_version": (ubody.get("document") or {}).get("active_version")
                if isinstance(ubody.get("document"), dict)
                else ubody.get("active_version"),
            }
        )

        # Query after update — expect eight hours if answered
        q2 = client.post(
            "/api/query",
            json={
                "question": (
                    "How long did PaymentService timeouts last "
                    "after the auth-gateway deploy?"
                ),
                "mode": "hybrid_rerank",
            },
        )
        q2b = q2.json() if q2.status_code == 200 else {}
        ans2 = (q2b.get("answer") or "").lower()
        out["steps"].append(
            {
                "step": "query_after_update",
                "status": q2.status_code,
                "answer_status": q2b.get("status"),
                "mentions_eight": "eight" in ans2 or "8" in ans2,
                "answer_preview": (q2b.get("answer") or "")[:240],
            }
        )

        if skip_delete:
            out["steps"].append(
                {
                    "step": "delete",
                    "status": 0,
                    "skipped": True,
                    "note": "deferred until after Render restart persistence check",
                }
            )
        else:
            dele = client.delete(
                f"/api/documents/{doc_id}",
                headers=_redact_headers(admin_token),
            )
            out["steps"].append({"step": "delete", "status": dele.status_code})

            gone = client.get(f"/api/documents/{doc_id}")
            out["steps"].append(
                {
                    "step": "get_after_delete",
                    "status": gone.status_code,
                    "ok_gone": gone.status_code in (404, 410)
                    or (
                        gone.status_code == 200
                        and (gone.json() or {}).get("status") == "DELETED"
                    ),
                }
            )

        # Rate limit: burn burst with rapid queries (best-effort)
        limited = False
        for _ in range(40):
            r = client.post("/api/query", json={"question": "ping rate limit"})
            if r.status_code == 429:
                limited = True
                break
        out["steps"].append({"step": "rate_limit_probe", "got_429": limited})

        metrics = client.get("/api/metrics")
        out["metrics"] = metrics.json() if metrics.status_code == 200 else {}

    out["document_id"] = doc_id
    required = ["upload", "chunks", "query", "update", "query_after_update"]
    if not skip_delete:
        required.append("delete")
    out["ok"] = all(
        s.get("status", 500) < 400 for s in out["steps"] if s["step"] in required
    ) and out["steps"][1].get("ok") is True
    return out


def persist_check(base: str, doc_id: str, admin_token: str) -> dict[str, Any]:
    timeout = httpx.Timeout(120.0, connect=60.0)
    with httpx.Client(base_url=base, timeout=timeout) as client:
        ready = client.get("/api/health/ready")
        got = client.get(f"/api/documents/{doc_id}")
        body = got.json() if got.status_code == 200 else {}
        return {
            "ready_status": ready.status_code,
            "ready_database": (ready.json() or {}).get("database"),
            "get_status": got.status_code,
            "doc_status": body.get("status"),
            "active_version": body.get("active_version"),
            "persisted_ok": got.status_code == 200
            and body.get("status") not in (None, "DELETED"),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("PROD_BASE_URL", DEFAULT_BASE))
    parser.add_argument("--phase", choices=["full", "persist"], default="full")
    parser.add_argument("--doc-id", default="")
    parser.add_argument(
        "--skip-delete",
        action="store_true",
        help="Keep uploaded doc for cross-restart persistence check",
    )
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()
    admin = _secret(settings, "admin_token")
    if not admin:
        print("ADMIN_TOKEN missing in .env — cannot mutate production documents")
        return 2

    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "phase": args.phase,
        "base": args.base,
    }

    if args.phase == "persist":
        if not args.doc_id:
            print("--doc-id required for persist phase")
            return 2
        report["persist"] = persist_check(args.base, args.doc_id, admin)
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        prev = {}
        if EVIDENCE.exists():
            prev = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        prev["persist_after_restart"] = report["persist"]
        prev["persist_checked_at"] = report["timestamp"]
        EVIDENCE.write_text(json.dumps(prev, indent=2), encoding="utf-8")
        print(json.dumps(report["persist"], indent=2))
        return 0 if report["persist"].get("persisted_ok") else 1

    report["neon"] = check_neon(settings)
    report["qdrant"] = check_qdrant(settings)
    report["embeddings"] = check_embeddings()
    report["api_e2e"] = api_e2e(args.base, admin, skip_delete=args.skip_delete)

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    # Also write a short pointer for the restart phase
    (ROOT / "docs" / "evidence" / "prod_checkpoint_doc_id.txt").write_text(
        str(report["api_e2e"].get("document_id") or ""),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "neon_ok": report["neon"].get("ok"),
                "qdrant_ok": report["qdrant"].get("ok"),
                "qdrant_collection": report["qdrant"].get("collection"),
                "qdrant_points": report["qdrant"].get("points_count"),
                "embeddings_ok": report["embeddings"].get("ok"),
                "api_ok": report["api_e2e"].get("ok"),
                "document_id": report["api_e2e"].get("document_id"),
                "evidence": str(EVIDENCE),
            },
            indent=2,
        )
    )
    ok = (
        report["neon"].get("ok")
        and report["qdrant"].get("ok")
        and report["embeddings"].get("ok")
        and report["api_e2e"].get("ok")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
