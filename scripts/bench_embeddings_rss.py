"""Measure FastAPI + fastembed peak RSS and query latency.

Writes docs/evidence/embedding_rss_bench.json from a real run.
Does not finalize the production embedding strategy.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import psutil


@dataclass
class BenchResult:
    timestamp: str
    model: str
    platform: str
    pid: int
    rss_before_mb: float
    rss_after_import_mb: float
    rss_after_model_load_mb: float
    rss_after_warmup_mb: float
    rss_peak_mb: float
    query_latency_ms_p50: float
    query_latency_ms_p95: float
    query_latency_ms_mean: float
    n_queries: int
    render_free_ram_mb: int
    headroom_vs_render_mb: float
    fits_render_512_with_50mb_headroom: bool
    notes: str


def _rss_mb(proc: psutil.Process) -> float:
    return proc.memory_info().rss / (1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--queries", type=int, default=20)
    parser.add_argument(
        "--out",
        default="docs/evidence/embedding_rss_bench.json",
    )
    args = parser.parse_args()

    proc = psutil.Process(os.getpid())
    peak = _rss_mb(proc)
    rss_before = peak

    # Import FastAPI stack (lightweight compared to ONNX).
    from fastapi import FastAPI  # noqa: F401
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    rss_after_import = _rss_mb(proc)
    peak = max(peak, rss_after_import)

    from app.embeddings.fastembed_provider import FastEmbedProvider

    provider = FastEmbedProvider(model_name=args.model)
    rss_after_load = _rss_mb(proc)
    peak = max(peak, rss_after_load)

    # Warmup
    _ = provider.embed_query("warmup query about payment processing incidents")
    rss_after_warmup = _rss_mb(proc)
    peak = max(peak, rss_after_warmup)

    latencies: list[float] = []
    samples = [
        "Which system changes caused disruptions in payment processing in March?",
        "What services were affected by the incident?",
        "When was the root cause corrected?",
        "Compare two documents about the same outage",
        "Is there evidence for service X downtime?",
    ]
    for i in range(args.queries):
        q = samples[i % len(samples)] + f" #{i}"
        t0 = time.perf_counter()
        vec = provider.embed_query(q)
        dt_ms = (time.perf_counter() - t0) * 1000
        latencies.append(dt_ms)
        assert len(vec) == provider.dimensions
        peak = max(peak, _rss_mb(proc))

    latencies_sorted = sorted(latencies)
    p50 = statistics.median(latencies_sorted)
    p95 = latencies_sorted[max(0, int(0.95 * (len(latencies_sorted) - 1)))]
    mean = statistics.fmean(latencies_sorted)

    render_ram = 512
    headroom = render_ram - peak
    fits = peak <= (render_ram - 50)

    result = BenchResult(
        timestamp=datetime.now(UTC).isoformat(),
        model=args.model,
        platform=f"{os.name}/{sys.platform}",
        pid=os.getpid(),
        rss_before_mb=round(rss_before, 2),
        rss_after_import_mb=round(rss_after_import, 2),
        rss_after_model_load_mb=round(rss_after_load, 2),
        rss_after_warmup_mb=round(rss_after_warmup, 2),
        rss_peak_mb=round(peak, 2),
        query_latency_ms_p50=round(p50, 2),
        query_latency_ms_p95=round(p95, 2),
        query_latency_ms_mean=round(mean, 2),
        n_queries=args.queries,
        render_free_ram_mb=render_ram,
        headroom_vs_render_mb=round(headroom, 2),
        fits_render_512_with_50mb_headroom=fits,
        notes=(
            "Local process RSS on developer machine; Render cgroup limits may differ. "
            "Production embedding strategy remains unfinalized until this gate is reviewed."
        ),
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(asdict(result), indent=2))
    if not fits:
        print(
            "\nGATE: peak RSS does not fit Render Free 512 MB with 50 MB headroom. "
            "Evaluate remote/smaller embedding alternatives before finalizing D5.",
            flush=True,
        )


if __name__ == "__main__":
    main()
