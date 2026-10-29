"""Benchmark the Docker image under a 512 MB memory ceiling (Render Free simulation).

Requires Docker Engine. Writes docs/evidence/container_512m_bench.json.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

IMAGE = "ai-investigation-engine:local"
CONTAINER = "aie-phase1-bench"
PORT = 18080
MEMORY = "512m"


@dataclass
class ContainerBench:
    timestamp: str
    image: str
    memory_limit: str
    docker_engine_ok: bool
    build_ok: bool
    container_started: bool
    oom_killed: bool
    startup_to_health_ms: float | None
    startup_to_ready_ms: float | None
    embedding_load_ms_reported: float | None
    embed_latency_ms_samples: list[float]
    embed_latency_ms_p50: float | None
    embed_latency_ms_mean: float | None
    docker_stats_peak_mem_usage_mb: float | None
    docker_stats_peak_mem_perc: float | None
    health_ok: bool
    ready_ok: bool
    notes: str


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def http_json(
    url: str, method: str = "GET", timeout: float = 30.0
) -> tuple[int, dict[str, object]]:
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else {}


def parse_mem(usage: str) -> float:
    # e.g. "256.5MiB" / "1.2GiB"
    usage = usage.strip()
    if usage.endswith("GiB"):
        return float(usage[:-3]) * 1024
    if usage.endswith("MiB"):
        return float(usage[:-3])
    if usage.endswith("KiB"):
        return float(usage[:-3]) / 1024
    if usage.endswith("B"):
        return float(usage[:-1]) / (1024 * 1024)
    return float(usage)


def main() -> None:
    notes: list[str] = []
    result = ContainerBench(
        timestamp=datetime.now(UTC).isoformat(),
        image=IMAGE,
        memory_limit=MEMORY,
        docker_engine_ok=False,
        build_ok=False,
        container_started=False,
        oom_killed=False,
        startup_to_health_ms=None,
        startup_to_ready_ms=None,
        embedding_load_ms_reported=None,
        embed_latency_ms_samples=[],
        embed_latency_ms_p50=None,
        embed_latency_ms_mean=None,
        docker_stats_peak_mem_usage_mb=None,
        docker_stats_peak_mem_perc=None,
        health_ok=False,
        ready_ok=False,
        notes="",
    )

    ver = run(["docker", "version", "--format", "{{.Server.Version}}"])
    result.docker_engine_ok = ver.returncode == 0 and bool(ver.stdout.strip())
    if not result.docker_engine_ok:
        result.notes = "Docker Engine not available"
        _write(result)
        raise SystemExit(1)

    # Ensure previous container is gone
    run(["docker", "rm", "-f", CONTAINER], check=False)

    t_build0 = time.perf_counter()
    build = run(["docker", "build", "-t", IMAGE, "."], check=False)
    if build.returncode != 0:
        result.notes = f"docker build failed:\n{build.stderr[-2000:]}"
        _write(result)
        raise SystemExit(1)
    result.build_ok = True
    notes.append(f"build_seconds={round(time.perf_counter() - t_build0, 1)}")

    run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER,
            "--memory",
            MEMORY,
            "--memory-swap",
            MEMORY,
            "-p",
            f"{PORT}:8000",
            "-e",
            "DATABASE_URL=sqlite+pysqlite:////tmp/app.db",
            "-e",
            "EMBEDDING_ENABLED_AT_STARTUP=true",
            "-e",
            "ENABLE_BENCH_ENDPOINTS=true",
            "-e",
            "APP_ENV=benchmark",
            IMAGE,
        ]
    )
    result.container_started = True

    base = f"http://127.0.0.1:{PORT}"
    t0 = time.perf_counter()
    health_deadline = t0 + 180
    while time.perf_counter() < health_deadline:
        try:
            status, _ = http_json(f"{base}/api/health", timeout=2)
            if status == 200:
                result.startup_to_health_ms = round((time.perf_counter() - t0) * 1000, 1)
                result.health_ok = True
                break
        except Exception:
            time.sleep(0.5)
        # Detect OOM
        inspect = run(
            ["docker", "inspect", "-f", "{{.State.OOMKilled}} {{.State.Status}}", CONTAINER],
            check=False,
        )
        if "true" in inspect.stdout:
            result.oom_killed = True
            break
        if "exited" in inspect.stdout:
            logs = run(["docker", "logs", CONTAINER], check=False)
            notes.append("container exited early")
            notes.append(logs.stdout[-1500:] + logs.stderr[-500:])
            break

    peak_mem = 0.0
    peak_perc = 0.0
    if result.health_ok and not result.oom_killed:
        ready_deadline = time.perf_counter() + 180
        while time.perf_counter() < ready_deadline:
            try:
                status, body = http_json(f"{base}/api/health/ready", timeout=5)
                if status == 200 and body.get("embedding_loaded") is True:
                    result.startup_to_ready_ms = round((time.perf_counter() - t0) * 1000, 1)
                    load_ms = body.get("embedding_load_ms")
                    result.embedding_load_ms_reported = (
                        float(load_ms) if isinstance(load_ms, (int, float)) else None
                    )
                    result.ready_ok = True
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                pass
            time.sleep(0.5)
            inspect = run(
                ["docker", "inspect", "-f", "{{.State.OOMKilled}} {{.State.Status}}", CONTAINER],
                check=False,
            )
            if "true" in inspect.stdout:
                result.oom_killed = True
                break

        samples: list[float] = []
        for i in range(15):
            stats = run(
                [
                    "docker",
                    "stats",
                    CONTAINER,
                    "--no-stream",
                    "--format",
                    "{{.MemUsage}}\t{{.MemPerc}}",
                ],
                check=False,
            )
            if stats.returncode == 0 and stats.stdout.strip():
                usage, perc = stats.stdout.strip().split("\t")
                usage_mb = parse_mem(usage.split("/")[0].strip())
                peak_mem = max(peak_mem, usage_mb)
                peak_perc = max(peak_perc, float(perc.replace("%", "")))
            try:
                status, body = http_json(
                    f"{base}/api/bench/embed?q=payment+incident+march+{i}",
                    method="POST",
                    timeout=30,
                )
                if status == 200 and "latency_ms" in body:
                    samples.append(float(body["latency_ms"]))  # type: ignore[arg-type]
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                notes.append(f"embed_error_{i}={exc}")
                inspect = run(
                    ["docker", "inspect", "-f", "{{.State.OOMKilled}}", CONTAINER],
                    check=False,
                )
                if "true" in inspect.stdout:
                    result.oom_killed = True
                    break
        result.embed_latency_ms_samples = [round(x, 3) for x in samples]
        if samples:
            ordered = sorted(samples)
            result.embed_latency_ms_p50 = round(ordered[len(ordered) // 2], 3)
            result.embed_latency_ms_mean = round(sum(samples) / len(samples), 3)
        result.docker_stats_peak_mem_usage_mb = round(peak_mem, 2) if peak_mem else None
        result.docker_stats_peak_mem_perc = round(peak_perc, 2) if peak_perc else None

    logs = run(["docker", "logs", CONTAINER], check=False)
    Path("docs/evidence/container_512m_logs.txt").write_text(
        logs.stdout + "\n" + logs.stderr,
        encoding="utf-8",
    )
    run(["docker", "rm", "-f", CONTAINER], check=False)

    if result.oom_killed:
        notes.append("OOMKilled under 512m — do not enable in-process BGE-small on Render Free")
    elif result.ready_ok and result.docker_stats_peak_mem_usage_mb is not None:
        if result.docker_stats_peak_mem_usage_mb > 450:
            notes.append("Peak memory >450 MiB — thin headroom on Render Free")
        else:
            notes.append("Provisional pass under 512m docker memory limit")
    result.notes = "; ".join(notes)
    _write(result)
    print(json.dumps(asdict(result), indent=2))
    if result.oom_killed or not result.ready_ok:
        raise SystemExit(2)


def _write(result: ContainerBench) -> None:
    path = Path("docs/evidence/container_512m_bench.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
