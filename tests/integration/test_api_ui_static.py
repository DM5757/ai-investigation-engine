"""Static UI serving smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_index_html(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "AI Investigation Engine" in res.text
    assert 'src="/static/app.js"' in res.text
    assert "Sample investigations" in res.text
    assert 'id="progress"' in res.text
    assert 'data-tab="eval"' in res.text


def test_static_app_js(client: TestClient) -> None:
    res = client.get("/static/app.js")
    assert res.status_code == 200
    assert "textContent" in res.text or "setText" in res.text
    assert "SAMPLES" in res.text
    assert "FraudScorer CPU usage" in res.text
    assert "startProgress" in res.text
    assert "localStorage.setItem" not in res.text
    assert "sessionStorage" not in res.text


def test_static_css(client: TestClient) -> None:
    res = client.get("/static/style.css")
    assert res.status_code == 200
    assert "status-badge" in res.text
    assert "sample-chip" in res.text
    assert "prefers-reduced-motion" in res.text


def test_security_headers(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert "access-control-allow-origin" not in {k.lower() for k in res.headers}


def test_stats_and_eval_runs(client: TestClient) -> None:
    stats = client.get("/api/stats")
    assert stats.status_code == 200
    assert "documents_by_status" in stats.json()

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert "queries" in metrics.json()

    ev = client.get("/api/eval/runs")
    assert ev.status_code == 200
    body = ev.json()
    assert isinstance(body.get("runs"), list)
    assert len(body["runs"]) >= 1
    assert "limitations" in body
    run_ids = {r.get("run_id") for r in body["runs"]}
    assert "m7_test_adapt_v3" in run_ids
    assert "full55k_retrieval_v1" in run_ids
    answer = next(r for r in body["runs"] if r["run_id"] == "m7_test_adapt_v3")
    cfg = answer["configs"][0]
    assert cfg["n_scored_answer"] == 62
    assert abs(float(cfg["token_f1"]) - 0.183) < 0.001
    assert "smoke" not in (body.get("note") or "").lower() or "not overall" in (
        body.get("note") or ""
    ).lower()
