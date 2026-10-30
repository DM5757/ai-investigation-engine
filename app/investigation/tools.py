"""Read-only investigation tools with schema-validated execution."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.index.qdrant_store import ChunkStore
from app.investigation.injection import scan_injection
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievalHit
from app.schemas.evidence import Finding

ToolName = Literal[
    "search_documents",
    "read_chunk_context",
    "get_document_metadata",
    "find_documents",
    "record_finding",
]


class SearchDocumentsArgs(BaseModel):
    query: str
    k: int = 5


class ReadChunkContextArgs(BaseModel):
    chunk_id: str
    window: int = 1


class GetDocumentMetadataArgs(BaseModel):
    doc_id: str


class FindDocumentsArgs(BaseModel):
    title_contains: str = ""
    limit: int = 10


class RecordFindingArgs(BaseModel):
    text: str
    related_chunk_ids: list[str] = Field(default_factory=list)
    related_doc_ids: list[str] = Field(default_factory=list)


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Hybrid search over indexed document chunks.",
            "parameters": SearchDocumentsArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_chunk_context",
            "description": "Read a chunk and neighboring chunks from the same document.",
            "parameters": ReadChunkContextArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_metadata",
            "description": "Return metadata fields for a document id.",
            "parameters": GetDocumentMetadataArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_documents",
            "description": "Find documents whose title contains a substring.",
            "parameters": FindDocumentsArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_finding",
            "description": "Record an intermediate investigation finding.",
            "parameters": RecordFindingArgs.model_json_schema(),
        },
    },
]


@dataclass
class ToolState:
    """Mutable investigation scratchpad shared across tool calls."""

    findings: list[Finding] = field(default_factory=list)
    retrieved: list[RetrievalHit] = field(default_factory=list)
    chunk_texts: dict[str, str] = field(default_factory=dict)
    flagged_chunk_ids: set[str] = field(default_factory=set)
    finding_seq: int = 0


@dataclass
class ToolExecutor:
    """Execute typed read-only tools against retriever + chunk store."""

    retriever: HybridRetriever
    store: ChunkStore
    state: ToolState = field(default_factory=ToolState)
    top_k: int = 8
    tau_retrieval: float = 0.0
    tau_relative: float = 0.35
    injection_downweight: float = 0.05
    last_timings: dict[str, float] = field(default_factory=dict)
    # Optional wall-clock / call budget gate (e.g. BudgetTracker.check).
    before_call: Callable[[], None] | None = None

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.before_call is not None:
            self.before_call()
        self.last_timings = {}
        try:
            if name == "search_documents":
                return self._search(SearchDocumentsArgs.model_validate(arguments))
            if name == "read_chunk_context":
                return self._read_context(ReadChunkContextArgs.model_validate(arguments))
            if name == "get_document_metadata":
                return self._metadata(GetDocumentMetadataArgs.model_validate(arguments))
            if name == "find_documents":
                return self._find(FindDocumentsArgs.model_validate(arguments))
            if name == "record_finding":
                return self._record(RecordFindingArgs.model_validate(arguments))
        except ValidationError as exc:
            return {"error": "invalid_args", "detail": str(exc)}
        return {"error": "unknown_tool", "name": name}

    def _search(self, args: SearchDocumentsArgs) -> dict[str, Any]:
        k = max(1, min(args.k, self.top_k))
        # Over-fetch then apply absolute + relative score floors before capping.
        fetch_k = max(k, min(self.top_k * 3, 24))
        hits = self.retriever.retrieve(args.query, k=fetch_k)
        self.last_timings = dict(getattr(self.retriever, "last_timings", {}) or {})
        scores = [float(hit.fused_score or hit.chunk.score or 0.0) for hit in hits]
        max_score = max(scores) if scores else 0.0
        rel_floor = max_score * max(0.0, min(1.0, self.tau_relative)) if max_score else 0.0
        floor = max(self.tau_retrieval, rel_floor)

        results: list[dict[str, Any]] = []
        for hit in hits:
            score = float(hit.fused_score or hit.chunk.score or 0.0)
            if score < floor and score < self.tau_retrieval:
                continue
            if floor > 0 and score < floor:
                continue
            scan = scan_injection(hit.chunk.text)
            if scan.flagged:
                self.state.flagged_chunk_ids.add(hit.chunk.chunk_id)
                score *= self.injection_downweight
            self.state.chunk_texts[hit.chunk.chunk_id] = hit.chunk.text
            self.state.retrieved.append(hit)
            results.append(
                {
                    "chunk_id": hit.chunk.chunk_id,
                    "doc_id": hit.chunk.doc_id,
                    "score": score,
                    "title": hit.chunk.title,
                    "text": scan.wrapped_text if not scan.flagged else scan.wrapped_text,
                    "injection_flagged": scan.flagged,
                }
            )
            if len(results) >= k:
                break
        results.sort(key=lambda r: (-float(r["score"]), str(r["chunk_id"])))
        return {"results": results}

    def _read_context(self, args: ReadChunkContextArgs) -> dict[str, Any]:
        if args.chunk_id in self.state.flagged_chunk_ids:
            return {"error": "chunk_flagged_injection", "chunk_id": args.chunk_id}
        payloads = self.store.get_payloads([args.chunk_id])
        base = payloads.get(args.chunk_id)
        if base is None:
            return {"error": "not_found", "chunk_id": args.chunk_id}
        doc_id = str(base.get("doc_id", ""))
        idx = int(base.get("chunk_index", 0))
        window = max(0, min(args.window, 3))
        neighbor_ids = [
            f"{doc_id}:{i}" for i in range(max(0, idx - window), idx + window + 1)
        ]
        # Also try exact stored ids via list
        all_ids = self.store.list_point_ids_for_doc(doc_id)
        id_by_index: dict[int, str] = {}
        for pid in all_ids:
            pl = self.store.get_payloads([pid]).get(pid, {})
            id_by_index[int(pl.get("chunk_index", -1))] = pid
        chunks: list[dict[str, Any]] = []
        for i in range(max(0, idx - window), idx + window + 1):
            point_id = id_by_index.get(i)
            if point_id is None and i == idx:
                point_id = args.chunk_id
            if point_id is None:
                continue
            if point_id in self.state.flagged_chunk_ids:
                continue
            payload = self.store.get_payloads([point_id]).get(point_id)
            if payload is None:
                continue
            text = str(payload.get("text", ""))
            scan = scan_injection(text)
            if scan.flagged:
                self.state.flagged_chunk_ids.add(point_id)
                continue
            self.state.chunk_texts[point_id] = text
            chunks.append(
                {
                    "chunk_id": point_id,
                    "chunk_index": i,
                    "text": scan.wrapped_text,
                    "doc_id": doc_id,
                }
            )
        _ = neighbor_ids
        return {"chunks": chunks}

    def _metadata(self, args: GetDocumentMetadataArgs) -> dict[str, Any]:
        ids = self.store.list_point_ids_for_doc(args.doc_id)
        if not ids:
            return {"error": "not_found", "doc_id": args.doc_id}
        pl = self.store.get_payloads([ids[0]]).get(ids[0], {})
        return {
            "doc_id": args.doc_id,
            "title": pl.get("title"),
            "version": pl.get("version"),
            "chunk_count": len(ids),
            "content_hash": pl.get("content_hash"),
        }

    def _find(self, args: FindDocumentsArgs) -> dict[str, Any]:
        needle = args.title_contains.lower().strip()
        # Scan known retrieved payloads + store via retrieved docs
        seen: dict[str, dict[str, Any]] = {}
        for hit in self.state.retrieved:
            title = (hit.chunk.title or "").lower()
            if needle and needle not in title:
                continue
            seen[hit.chunk.doc_id] = {
                "doc_id": hit.chunk.doc_id,
                "title": hit.chunk.title,
                "version": hit.chunk.version,
            }
        docs = list(seen.values())[: max(1, args.limit)]
        return {"documents": docs}

    def _record(self, args: RecordFindingArgs) -> dict[str, Any]:
        self.state.finding_seq += 1
        finding = Finding(
            finding_id=f"f{self.state.finding_seq}",
            text=args.text,
            related_chunk_ids=list(args.related_chunk_ids),
            related_doc_ids=list(args.related_doc_ids),
        )
        self.state.findings.append(finding)
        return {"ok": True, "finding_id": finding.finding_id}


def tool_result_message(tool_call_id: str, payload: dict[str, Any]) -> dict[str, str]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(payload, ensure_ascii=True),
    }
