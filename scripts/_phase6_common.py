"""Shared helpers for Phase 6 corpus / ingest scripts (no secrets printed)."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_engine, get_session_factory  # noqa: E402
from app.embeddings.fastembed_provider import FastEmbedProvider  # noqa: E402
from app.index.qdrant_store import ChunkStore, QdrantChunkStore, make_local_chunk_store  # noqa: E402
from app.ingestion.lifecycle import DocumentLifecycle  # noqa: E402
from app.ingestion.pipeline import PreparedDocument, prepare_document  # noqa: E402
from app.retrieval.bm25_sparse import Bm25Encoder  # noqa: E402

DATA_DIR = ROOT / "data"
RAW_CORPUS = DATA_DIR / "raw" / "corpus.jsonl"
CORPUS_MANIFEST = DATA_DIR / "manifests" / "corpus_manifest.json"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
SYNTHETIC_TRUTH = DATA_DIR / "manifests" / "synthetic_truth.json"
EVIDENCE_DIR = ROOT / "docs" / "evidence"
SAMPLE_CORPUS = DATA_DIR / "samples" / "hotpot_sample.jsonl"

# Free-tier headroom targets (leave margin; see FREE_TIER_NOTES.md).
NEON_CAP_BYTES = 1_000_000_000
NEON_SAFE_BYTES = 750_000_000  # ~75% of 1 GB
QDRANT_DISK_CAP_BYTES = 4_000_000_000
QDRANT_DISK_SAFE_BYTES = 3_000_000_000  # ~75% of 4 GB
QDRANT_RAM_CAP_BYTES = 1_000_000_000
QDRANT_RAM_SAFE_BYTES = 700_000_000  # leave RAM margin


def ensure_dirs() -> None:
    for path in (
        DATA_DIR / "raw",
        DATA_DIR / "manifests",
        DATA_DIR / "samples",
        DATA_DIR / "synthetic",
        DATA_DIR / "checkpoints",
        EVIDENCE_DIR,
        ROOT / "eval" / "results",
        ROOT / "docs" / "phase_notes",
    ):
        path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            obj = json.loads(stripped)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no} must be a JSON object")
            yield obj


def build_store(settings: Settings) -> ChunkStore:
    if settings.qdrant_url:
        api_key = (
            settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        )
        store: ChunkStore = QdrantChunkStore.remote(
            settings.qdrant_url,
            api_key=api_key,
            strategy=settings.chunk_strategy,
            embedding_short=settings.embedding_model_short,
            dense_size=settings.dense_vector_size,
        )
        store.ensure_collection()
        return store
    local = make_local_chunk_store(
        path=settings.qdrant_path,
        strategy=settings.chunk_strategy,
        embedding_short=settings.embedding_model_short,
        dense_size=settings.dense_vector_size,
    )
    local.ensure_collection()
    return local


def open_session(settings: Settings) -> Session:
    engine = get_engine(settings.database_url)
    Base.metadata.create_all(engine)
    return get_session_factory(settings.database_url)()


def make_lifecycle(
    session: Session,
    store: ChunkStore,
    settings: Settings,
    *,
    embedder: FastEmbedProvider | None = None,
    avgdl: float | None = None,
    check_near_duplicates: bool = True,
) -> DocumentLifecycle:
    provider = embedder or FastEmbedProvider(model_name=settings.embedding_model)
    encoder = Bm25Encoder(
        k1=settings.bm25_k1,
        b=settings.bm25_b,
        avgdl=avgdl if avgdl is not None else settings.bm25_avgdl,
    )

    def _embed(texts: list[str]) -> list[list[float]]:
        return provider.embed_documents(list(texts))

    return DocumentLifecycle(
        session,
        store,
        chunk_strategy=settings.chunk_strategy,
        simhash_threshold=settings.simhash_threshold,
        near_duplicate_policy=settings.near_duplicate_policy,
        embed_fn=_embed,
        sparse_encoder=encoder,
        dense_dims=settings.dense_vector_size,
        check_near_duplicates=check_near_duplicates,
    )


def record_to_prepared(
    record: dict[str, Any],
    *,
    chunk_strategy: str,
    chunk_tokens: int,
    overlap_tokens: int,
) -> PreparedDocument:
    """Build a PreparedDocument from a corpus JSONL record (no file parse)."""
    from app.ingestion.parsers.base import ParsedDocument, single_span

    text = str(record.get("text") or "").strip()
    if not text:
        raise ValueError("record missing text")
    title = str(record.get("title") or record.get("id") or "untitled")
    meta = dict(record.get("meta") or {})
    meta.setdefault("source_type", "jsonl")
    meta.setdefault("origin", "hotpotqa")
    meta.setdefault("corpus_id", record.get("id"))
    filename = f"{title}.jsonl"
    # prepare_document via synthetic parse_fn
    parsed = ParsedDocument(
        text=text,
        title=title,
        metadata=meta,
        spans=single_span(text),
    )

    def parse_fn(_filename: str, _data: bytes) -> ParsedDocument:
        return parsed

    return prepare_document(
        filename,
        text.encode("utf-8"),
        chunk_strategy=chunk_strategy,
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
        parse_fn=parse_fn,
    )


def neon_database_size_bytes(settings: Settings) -> dict[str, Any]:
    """Query Neon/Postgres database size. Returns bytes when available."""
    engine = get_engine(settings.database_url)
    out: dict[str, Any] = {"ok": False}
    with engine.connect() as conn:
        dialect = conn.dialect.name
        out["dialect"] = dialect
        if dialect == "postgresql":
            size = conn.execute(text("SELECT pg_database_size(current_database())")).scalar()
            name = conn.execute(text("SELECT current_database()")).scalar()
            out["ok"] = True
            out["database"] = name
            out["size_bytes"] = int(size or 0)
            out["size_mb"] = round(int(size or 0) / (1024 * 1024), 3)
        else:
            # SQLite fallback — file size if file DB
            url = settings.database_url
            out["note"] = "pg_database_size unavailable for non-Postgres"
            out["database_url_scheme"] = url.split("://", 1)[0]
            out["ok"] = True
            out["size_bytes"] = None
    return out


def neon_doc_counts(settings: Settings) -> dict[str, Any]:
    engine = get_engine(settings.database_url)
    with engine.connect() as conn:
        active = conn.execute(
            text("SELECT count(*) FROM documents WHERE status = 'ACTIVE'")
        ).scalar()
        non_deleted = conn.execute(
            text("SELECT count(*) FROM documents WHERE status != 'DELETED'")
        ).scalar()
        chunks = conn.execute(text("SELECT count(*) FROM chunks")).scalar()
        by_status_rows = conn.execute(
            text("SELECT status, count(*) FROM documents GROUP BY status")
        ).fetchall()
    return {
        "active_documents": int(active or 0),
        "non_deleted_documents": int(non_deleted or 0),
        "chunk_rows": int(chunks or 0),
        "by_status": {str(r[0]): int(r[1]) for r in by_status_rows},
    }


def qdrant_collection_stats(store: ChunkStore) -> dict[str, Any]:
    """Point count + disk/RAM when Qdrant API exposes them."""
    out: dict[str, Any] = {"ok": False, "collection": getattr(store, "collection", None)}
    client = getattr(store, "client", None)
    collection = getattr(store, "collection", None)
    if client is None or collection is None:
        out["error"] = "store has no Qdrant client (in-memory?)"
        return out
    try:
        count = int(client.count(collection_name=collection, exact=True).count)
        info = client.get_collection(collection)
        out["ok"] = True
        out["points_count"] = count
        out["status"] = str(getattr(info, "status", ""))
        # Best-effort disk/RAM from cluster or collection APIs (version-dependent).
        disk_bytes: int | None = None
        ram_bytes: int | None = None
        for attr in ("disk_data_size", "segments_count"):
            val = getattr(info, attr, None)
            if attr == "disk_data_size" and val is not None:
                disk_bytes = int(val)
        # Newer clients: info.payload / optimizer status
        meta = getattr(info, "model_dump", None)
        dumped: dict[str, Any] = {}
        if callable(meta):
            try:
                dumped = meta()
            except Exception:  # noqa: BLE001
                dumped = {}
        # Try cluster telemetry if available
        try:
            telemetry = client.http.telemetry  # type: ignore[attr-defined]
            if telemetry is not None:
                out["telemetry_available"] = True
        except Exception:  # noqa: BLE001
            out["telemetry_available"] = False
        # Collection info nested fields
        if isinstance(dumped, dict):
            for key in ("disk_data_size", "vectors_count", "indexed_vectors_count"):
                if key in dumped and dumped[key] is not None:
                    out[key] = dumped[key]
            # Some versions put sizes under "status" or "optimizer"
        # Cluster info endpoint
        try:
            cluster = client.http.cluster_api.cluster_status()  # type: ignore[attr-defined]
            out["cluster_status"] = str(cluster)
        except Exception:  # noqa: BLE001
            pass
        try:
            # qdrant-client: get_collection returns CollectionInfo with points_count sometimes
            pc = getattr(info, "points_count", None)
            if pc is not None:
                out["points_count_info"] = int(pc)
        except Exception:  # noqa: BLE001
            pass
        # Approximate RAM from dense vectors if sizes unavailable
        dense_size = getattr(store, "dense_size", 384)
        approx_dense = count * int(dense_size) * 4
        out["approx_dense_vector_bytes"] = approx_dense
        out["disk_bytes"] = disk_bytes
        out["ram_bytes"] = ram_bytes
        out["disk_bytes_source"] = "api" if disk_bytes is not None else "unavailable"
        out["ram_bytes_source"] = "api" if ram_bytes is not None else "unavailable"
        # Fallback estimate for planning (not claimed as measured API)
        out["estimated_disk_bytes_lower_bound"] = approx_dense + count * 700
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def estimate_from_pilot(
    *,
    pilot_docs: int,
    pilot_neon_bytes: int | None,
    pilot_qdrant_points: int,
    pilot_estimated_qdrant_disk: int | None,
    pilot_wall_s: float,
    target_docs: int = 55_000,
) -> dict[str, Any]:
    if pilot_docs <= 0:
        raise ValueError("pilot_docs must be > 0")
    scale = target_docs / pilot_docs
    neon_est = int(pilot_neon_bytes * scale) if pilot_neon_bytes is not None else None
    q_disk = (
        int(pilot_estimated_qdrant_disk * scale)
        if pilot_estimated_qdrant_disk is not None
        else None
    )
    points_est = int(round(pilot_qdrant_points * scale))
    # RAM rough: dense vectors if fully resident
    ram_est = points_est * 384 * 4

    reasons: list[str] = []
    go = True
    if neon_est is not None and neon_est > NEON_SAFE_BYTES:
        go = False
        reasons.append(
            f"Neon estimate {neon_est} bytes exceeds safe headroom {NEON_SAFE_BYTES}"
        )
    if q_disk is not None and q_disk > QDRANT_DISK_SAFE_BYTES:
        go = False
        reasons.append(
            f"Qdrant disk estimate {q_disk} exceeds safe headroom {QDRANT_DISK_SAFE_BYTES}"
        )
    if ram_est > QDRANT_RAM_SAFE_BYTES:
        # Soft warning — on-disk may help; still flag if far over
        if ram_est > QDRANT_RAM_CAP_BYTES:
            go = False
            reasons.append(
                f"Qdrant RAM lower-bound {ram_est} exceeds 1 GB cap "
                "(dense vectors if fully in RAM)"
            )
        else:
            reasons.append(
                f"Qdrant RAM lower-bound {ram_est} above preferred margin "
                f"{QDRANT_RAM_SAFE_BYTES}; prefer on-disk / monitor"
            )

    # Max safe docs from tightest constraint
    max_safe = target_docs
    if pilot_neon_bytes and pilot_neon_bytes > 0:
        max_safe = min(max_safe, int(NEON_SAFE_BYTES / (pilot_neon_bytes / pilot_docs)))
    if pilot_estimated_qdrant_disk and pilot_estimated_qdrant_disk > 0:
        max_safe = min(
            max_safe,
            int(QDRANT_DISK_SAFE_BYTES / (pilot_estimated_qdrant_disk / pilot_docs)),
        )
    # RAM constraint assuming dense in RAM
    bytes_per_doc_ram = (pilot_qdrant_points / pilot_docs) * 384 * 4
    if bytes_per_doc_ram > 0:
        max_safe_ram = int(QDRANT_RAM_SAFE_BYTES / bytes_per_doc_ram)
        if max_safe_ram < max_safe:
            reasons.append(
                f"RAM margin caps ~{max_safe_ram} docs if dense vectors stay in RAM"
            )
            # Don't auto-fail go solely on soft RAM margin if disk/neon OK —
            # Free tier often uses mmap; use as proposed subset if go=False already
            if not go:
                max_safe = min(max_safe, max_safe_ram)

    wall_est_s = pilot_wall_s * scale if pilot_wall_s > 0 else None
    return {
        "target_docs": target_docs,
        "pilot_docs": pilot_docs,
        "scale_factor": round(scale, 4),
        "neon_bytes_estimate": neon_est,
        "neon_mb_estimate": round(neon_est / (1024 * 1024), 2) if neon_est else None,
        "qdrant_points_estimate": points_est,
        "qdrant_disk_bytes_estimate": q_disk,
        "qdrant_disk_mb_estimate": round(q_disk / (1024 * 1024), 2) if q_disk else None,
        "qdrant_ram_bytes_lower_bound": ram_est,
        "qdrant_ram_mb_lower_bound": round(ram_est / (1024 * 1024), 2),
        "wall_time_seconds_estimate": round(wall_est_s, 1) if wall_est_s else None,
        "neon_cap_bytes": NEON_CAP_BYTES,
        "neon_safe_bytes": NEON_SAFE_BYTES,
        "qdrant_disk_cap_bytes": QDRANT_DISK_CAP_BYTES,
        "qdrant_disk_safe_bytes": QDRANT_DISK_SAFE_BYTES,
        "qdrant_ram_cap_bytes": QDRANT_RAM_CAP_BYTES,
        "qdrant_ram_safe_bytes": QDRANT_RAM_SAFE_BYTES,
        "full_ingest_go": go,
        "reasons": reasons,
        "proposed_max_safe_docs": max(0, max_safe),
        "records_per_second_pilot": (
            round(pilot_docs / pilot_wall_s, 3) if pilot_wall_s > 0 else None
        ),
    }


def _ingest_one(
    lifecycle: DocumentLifecycle,
    session: Session,
    rec: dict[str, Any],
    *,
    idx: int,
    settings: Settings,
    outcomes: dict[str, int],
    errors: list[dict[str, str]],
) -> None:
    """Single-record lifecycle.add path (fallback / batch_size=1)."""
    ext = str(rec.get("id") or f"row-{idx}")
    try:
        prep = record_to_prepared(
            rec,
            chunk_strategy=settings.chunk_strategy,
            chunk_tokens=settings.chunk_tokens,
            overlap_tokens=settings.overlap_tokens,
        )
        result = lifecycle.add(
            prep.filename,
            b"",
            external_key=ext,
            prepared=prep,
        )
        key = str(result.outcome)
        outcomes[key] = outcomes.get(key, 0) + 1
        if key == "failed" and len(errors) < 20:
            errors.append(
                {
                    "id": ext,
                    "error": (result.message or "lifecycle failed")[:300],
                }
            )
    except Exception as exc:  # noqa: BLE001
        outcomes["error"] = outcomes.get("error", 0) + 1
        if len(errors) < 20:
            errors.append({"id": ext, "error": str(exc)[:300]})
        session.rollback()
        session.expire_all()


def _ingest_batch(
    lifecycle: DocumentLifecycle,
    session: Session,
    store: ChunkStore,
    batch: list[tuple[int, dict[str, Any]]],
    *,
    settings: Settings,
    outcomes: dict[str, int],
    errors: list[dict[str, str]],
) -> None:
    """Batched create → embed → Qdrant upsert → ACTIVE (fewer round-trips).

    Preserves external_key / content_hash semantics. Near-dup checks are skipped
    in this path (bulk default); use batch_size=1 with check_near_duplicates for
    full lifecycle behavior.
    """
    from app.db.models import DocumentStatus
    from app.index.qdrant_store import ChunkPoint

    prepared: list[tuple[str, Any]] = []
    for idx, rec in batch:
        ext = str(rec.get("id") or f"row-{idx}")
        try:
            prep = record_to_prepared(
                rec,
                chunk_strategy=settings.chunk_strategy,
                chunk_tokens=settings.chunk_tokens,
                overlap_tokens=settings.overlap_tokens,
            )
            prepared.append((ext, prep))
        except Exception as exc:  # noqa: BLE001
            outcomes["error"] = outcomes.get("error", 0) + 1
            if len(errors) < 20:
                errors.append({"id": ext, "error": str(exc)[:300]})

    if not prepared:
        return

    existing_by_key = lifecycle.docs.get_by_external_keys([ext for ext, _ in prepared])
    hashes = [prep.content_hash for _, prep in prepared]
    existing_by_hash = lifecycle.docs.find_by_content_hashes(hashes)

    to_create: list[tuple[str, Any]] = []
    to_finish: list[Any] = []  # INDEXING/PENDING docs that need index completion
    for ext, prep in prepared:
        existing = existing_by_key.get(ext)
        if existing is not None:
            status = str(existing.status)
            if existing.content_hash == prep.content_hash:
                if status in (
                    DocumentStatus.INDEXING,
                    DocumentStatus.PENDING,
                    DocumentStatus.FAILED,
                ):
                    # Interrupted batch left a non-ACTIVE row — finish indexing.
                    to_finish.append(existing)
                else:
                    outcomes["unchanged"] = outcomes.get("unchanged", 0) + 1
            else:
                # Content changed under same key — fall back to single-doc update.
                try:
                    result = lifecycle.update(ext, prep.filename, b"", prepared=prep)
                    key = str(result.outcome)
                    outcomes[key] = outcomes.get(key, 0) + 1
                except Exception as exc:  # noqa: BLE001
                    outcomes["error"] = outcomes.get("error", 0) + 1
                    if len(errors) < 20:
                        errors.append({"id": ext, "error": str(exc)[:300]})
                    session.rollback()
                    session.expire_all()
            continue
        exact = existing_by_hash.get(prep.content_hash)
        if exact is not None and exact.external_key != ext:
            outcomes["exact_duplicate"] = outcomes.get("exact_duplicate", 0) + 1
            continue
        to_create.append((ext, prep))

    # Complete interrupted INDEXING/PENDING/FAILED rows (real embeddings, not zeros).
    for doc in to_finish:
        try:
            version = doc.active_version if doc.active_version >= 1 else 1
            chunk_rows = lifecycle.chunks.list_for_version(doc.id, version)
            if not chunk_rows:
                # Version rows may exist under version 1 even if active_version=0
                chunk_rows = lifecycle.chunks.list_for_version(doc.id, 1)
                version = 1
            if not chunk_rows:
                outcomes["failed"] = outcomes.get("failed", 0) + 1
                continue
            lifecycle.docs.set_status(doc, DocumentStatus.INDEXING, clear_error=True)
            session.commit()
            texts = [r.text for r in chunk_rows]
            vectors = lifecycle.embed_fn(texts)
            points: list[ChunkPoint] = []
            for row, dense in zip(chunk_rows, vectors, strict=True):
                sparse_indices: list[int] = []
                sparse_values: list[float] = []
                if lifecycle.sparse_encoder is not None:
                    sparse = lifecycle.sparse_encoder.encode_document(row.text)
                    sparse_indices = sparse.indices
                    sparse_values = sparse.values
                points.append(
                    ChunkPoint(
                        point_id=row.qdrant_point_id,
                        doc_id=doc.id,
                        version=version,
                        chunk_index=row.chunk_index,
                        content_hash=row.content_hash,
                        text=row.text,
                        dense_vector=dense,
                        sparse_indices=sparse_indices,
                        sparse_values=sparse_values,
                        payload_extra={
                            "title": doc.title,
                            "heading_path": row.heading_path,
                            "near_duplicate_of": doc.near_duplicate_of,
                        },
                    )
                )
            store.upsert_chunks(points)
            lifecycle.docs.set_status(doc, DocumentStatus.ACTIVE, clear_error=True)
            lifecycle.docs.set_active_version(doc, version)
            session.commit()
            outcomes["created"] = outcomes.get("created", 0) + 1
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            outcomes["failed"] = outcomes.get("failed", 0) + 1
            if len(errors) < 20:
                errors.append({"id": str(doc.external_key or doc.id), "error": str(exc)[:300]})

    if not to_create:
        return

    # Dedup within batch by external_key / content_hash.
    seen_keys: set[str] = set()
    seen_hashes: set[str] = set()
    unique_create: list[tuple[str, Any]] = []
    for ext, prep in to_create:
        if ext in seen_keys:
            outcomes["unchanged"] = outcomes.get("unchanged", 0) + 1
            continue
        if prep.content_hash in seen_hashes:
            outcomes["exact_duplicate"] = outcomes.get("exact_duplicate", 0) + 1
            continue
        seen_keys.add(ext)
        seen_hashes.add(prep.content_hash)
        unique_create.append((ext, prep))

    pending_rows: list[tuple[Any, int, Any, list[Any]]] = []
    try:
        for ext, prep in unique_create:
            doc = lifecycle.docs.create(
                external_key=ext,
                filename=prep.filename,
                title=prep.title,
                content_hash=prep.content_hash,
                simhash=f"{prep.simhash:016x}",
                status=DocumentStatus.PENDING,
                active_version=0,
                metadata=prep.metadata,
            )
            version = 1
            lifecycle._persist_version_and_chunks(doc, version, prep)
            lifecycle.docs.replace_simhash_bands(
                doc.id,
                bands=prep.bands,
                simhash=f"{prep.simhash:016x}",
                content_hash=prep.content_hash,
            )
            lifecycle.docs.set_status(doc, DocumentStatus.INDEXING, clear_error=True)
            chunk_rows = lifecycle.chunks.list_for_version(doc.id, version)
            pending_rows.append((doc, version, prep, chunk_rows))
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        session.expire_all()
        # Fall back to single-doc path for this batch to preserve progress.
        outcomes["batch_fallback"] = outcomes.get("batch_fallback", 0) + 1
        if len(errors) < 20:
            errors.append({"id": "batch", "error": f"batch persist failed: {exc}"[:300]})
        for ext, prep in unique_create:
            try:
                result = lifecycle.add(prep.filename, b"", external_key=ext, prepared=prep)
                key = str(result.outcome)
                outcomes[key] = outcomes.get(key, 0) + 1
            except Exception as inner:  # noqa: BLE001
                outcomes["error"] = outcomes.get("error", 0) + 1
                if len(errors) < 20:
                    errors.append({"id": ext, "error": str(inner)[:300]})
                session.rollback()
                session.expire_all()
        return

    all_texts: list[str] = []
    for _doc, _ver, _prep, chunk_rows in pending_rows:
        for row in chunk_rows:
            all_texts.append(row.text)

    try:
        vectors = lifecycle.embed_fn(all_texts) if all_texts else []
        if len(vectors) != len(all_texts):
            raise RuntimeError(
                f"embed count mismatch: got {len(vectors)} for {len(all_texts)} texts"
            )
        points: list[ChunkPoint] = []
        vec_i = 0
        for doc, version, _prep, chunk_rows in pending_rows:
            for row in chunk_rows:
                dense = vectors[vec_i]
                vec_i += 1
                sparse_indices: list[int] = []
                sparse_values: list[float] = []
                if lifecycle.sparse_encoder is not None:
                    sparse = lifecycle.sparse_encoder.encode_document(row.text)
                    sparse_indices = sparse.indices
                    sparse_values = sparse.values
                points.append(
                    ChunkPoint(
                        point_id=row.qdrant_point_id,
                        doc_id=doc.id,
                        version=version,
                        chunk_index=row.chunk_index,
                        content_hash=row.content_hash,
                        text=row.text,
                        dense_vector=dense,
                        sparse_indices=sparse_indices,
                        sparse_values=sparse_values,
                        payload_extra={
                            "title": doc.title,
                            "heading_path": row.heading_path,
                            "near_duplicate_of": doc.near_duplicate_of,
                        },
                    )
                )
        store.upsert_chunks(points)
        for doc, version, _prep, _rows in pending_rows:
            lifecycle.docs.set_status(doc, DocumentStatus.ACTIVE, clear_error=True)
            lifecycle.docs.set_active_version(doc, version)
        session.commit()
        outcomes["created"] = outcomes.get("created", 0) + len(pending_rows)
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        for doc, _version, _prep, _rows in pending_rows:
            try:
                failed = lifecycle.docs.get(doc.id)
                if failed is not None:
                    lifecycle.docs.set_status(
                        failed, DocumentStatus.FAILED, error_message=str(exc)[:500]
                    )
            except Exception:  # noqa: BLE001
                pass
        session.commit()
        outcomes["failed"] = outcomes.get("failed", 0) + len(pending_rows)
        if len(errors) < 20:
            errors.append({"id": "batch_index", "error": str(exc)[:300]})


def _repair_incomplete_docs(
    lifecycle: DocumentLifecycle,
    session: Session,
    store: ChunkStore,
    outcomes: dict[str, int],
    errors: list[dict[str, str]],
    *,
    limit: int = 500,
) -> int:
    """Finish INDEXING/PENDING docs with real embeddings (not reconcile zero vectors)."""
    from app.db.models import DocumentStatus
    from app.index.qdrant_store import ChunkPoint

    docs = lifecycle.docs.list_by_status(
        DocumentStatus.INDEXING, DocumentStatus.PENDING
    )[:limit]
    repaired = 0
    for doc in docs:
        try:
            version = doc.active_version if doc.active_version >= 1 else 1
            chunk_rows = lifecycle.chunks.list_for_version(doc.id, version)
            if not chunk_rows:
                chunk_rows = lifecycle.chunks.list_for_version(doc.id, 1)
                version = 1
            if not chunk_rows:
                lifecycle.docs.set_status(
                    doc, DocumentStatus.FAILED, error_message="repair: no chunks"
                )
                session.commit()
                outcomes["failed"] = outcomes.get("failed", 0) + 1
                continue
            lifecycle.docs.set_status(doc, DocumentStatus.INDEXING, clear_error=True)
            session.commit()
            vectors = lifecycle.embed_fn([r.text for r in chunk_rows])
            points: list[ChunkPoint] = []
            for row, dense in zip(chunk_rows, vectors, strict=True):
                sparse_indices: list[int] = []
                sparse_values: list[float] = []
                if lifecycle.sparse_encoder is not None:
                    sparse = lifecycle.sparse_encoder.encode_document(row.text)
                    sparse_indices = sparse.indices
                    sparse_values = sparse.values
                points.append(
                    ChunkPoint(
                        point_id=row.qdrant_point_id,
                        doc_id=doc.id,
                        version=version,
                        chunk_index=row.chunk_index,
                        content_hash=row.content_hash,
                        text=row.text,
                        dense_vector=dense,
                        sparse_indices=sparse_indices,
                        sparse_values=sparse_values,
                        payload_extra={
                            "title": doc.title,
                            "heading_path": row.heading_path,
                            "near_duplicate_of": doc.near_duplicate_of,
                        },
                    )
                )
            store.upsert_chunks(points)
            lifecycle.docs.set_status(doc, DocumentStatus.ACTIVE, clear_error=True)
            lifecycle.docs.set_active_version(doc, version)
            session.commit()
            outcomes["repaired"] = outcomes.get("repaired", 0) + 1
            repaired += 1
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            outcomes["failed"] = outcomes.get("failed", 0) + 1
            if len(errors) < 20:
                errors.append(
                    {"id": str(doc.external_key or doc.id), "error": f"repair: {exc}"[:300]}
                )
    return repaired


def ingest_records(
    records: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
    throttle_s: float = 0.0,
    checkpoint_path: Path | None = None,
    checkpoint_every: int = 50,
    start_index: int = 0,
    check_near_duplicates: bool = True,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Ingest corpus records via DocumentLifecycle. Resumable via checkpoint.

    ``batch_size`` > 1 enables batched DB writes + embedding + Qdrant upserts.
    Near-duplicate SimHash checks run only when ``batch_size == 1`` and
    ``check_near_duplicates`` is True (bulk default disables near-dup).
    """
    settings = settings or get_settings()
    store = build_store(settings)
    session = open_session(settings)
    embedder = FastEmbedProvider(model_name=settings.embedding_model)
    use_batch = batch_size > 1 and not check_near_duplicates
    lifecycle = make_lifecycle(
        session,
        store,
        settings,
        embedder=embedder,
        check_near_duplicates=check_near_duplicates and not use_batch,
    )

    outcomes: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    t0 = time.perf_counter()
    processed = 0
    # Repair interrupted INDEXING/PENDING rows left by killed batch runs.
    repaired = _repair_incomplete_docs(lifecycle, session, store, outcomes, errors)
    if repaired:
        print(f"repaired_incomplete_docs={repaired} outcomes={outcomes}", flush=True)
    print(
        f"ingest start records={len(records)} start_index={start_index} "
        f"embedder={embedder.model_name} batch_size={batch_size if use_batch else 1}",
        flush=True,
    )
    try:
        idx = start_index
        while idx < len(records):
            if use_batch:
                end = min(idx + batch_size, len(records))
                batch = [(i, records[i]) for i in range(idx, end)]
                _ingest_batch(
                    lifecycle,
                    session,
                    store,
                    batch,
                    settings=settings,
                    outcomes=outcomes,
                    errors=errors,
                )
                step = end - idx
                idx = end
            else:
                _ingest_one(
                    lifecycle,
                    session,
                    records[idx],
                    idx=idx,
                    settings=settings,
                    outcomes=outcomes,
                    errors=errors,
                )
                step = 1
                idx += 1
            processed += step
            if processed == step or processed % 10 == 0 or (use_batch and step > 1):
                elapsed = time.perf_counter() - t0
                rps = processed / elapsed if elapsed > 0 else 0.0
                print(
                    f"ingest progress {start_index + processed}/{len(records)} "
                    f"rps={rps:.2f} outcomes={outcomes}",
                    flush=True,
                )
            if throttle_s > 0:
                time.sleep(throttle_s * step)
            if checkpoint_path and (
                processed % checkpoint_every == 0
                or (use_batch and processed % checkpoint_every < step)
                or idx >= len(records)
            ):
                write_json(
                    checkpoint_path,
                    {
                        "next_index": idx,
                        "processed": start_index + processed,
                        "outcomes": outcomes,
                        "batch_size": batch_size if use_batch else 1,
                        "updated_at": time.time(),
                    },
                )
    finally:
        session.close()

    wall = time.perf_counter() - t0
    if checkpoint_path:
        write_json(
            checkpoint_path,
            {
                "next_index": start_index + processed,
                "processed": start_index + processed,
                "outcomes": outcomes,
                "batch_size": batch_size if use_batch else 1,
                "done": start_index + processed >= len(records),
                "updated_at": time.time(),
            },
        )
    return {
        "attempted": processed,
        "start_index": start_index,
        "outcomes": outcomes,
        "errors_sample": errors,
        "wall_seconds": round(wall, 3),
        "records_per_second": round(processed / wall, 3) if wall > 0 else None,
        "batch_size": batch_size if use_batch else 1,
    }
