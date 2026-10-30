"""Trace stages must record real elapsed time for timed work."""

from __future__ import annotations

import time

from app.investigation.trace import TraceRecorder


def test_stage_context_uses_monotonic_elapsed() -> None:
    trace = TraceRecorder()
    with trace.stage("slow") as bag:
        time.sleep(0.05)
        bag["outputs_summary"] = "done"
    assert len(trace.events) == 1
    assert trace.events[0].latency_ms >= 40.0
