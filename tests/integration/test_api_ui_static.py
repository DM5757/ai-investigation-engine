"""Static UI serving smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_index_html(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "AI Investigation Engine" in res.text
    assert 'src="/static/app.js"' in res.text


def test_static_app_js(client: TestClient) -> None:
    res = client.get("/static/app.js")
    assert res.status_code == 200
    assert "textContent" in res.text or "setText" in res.text


def test_static_css(client: TestClient) -> None:
    res = client.get("/static/style.css")
    assert res.status_code == 200
    assert "status-badge" in res.text


def test_security_headers(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert "access-control-allow-origin" not in {k.lower() for k in res.headers}


def test_stats_and_eval_stub(client: TestClient) -> None:
    stats = client.get("/api/stats")
    assert stats.status_code == 200
    assert "documents_by_status" in stats.json()

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert "queries" in metrics.json()

    ev = client.get("/api/eval/runs")
    assert ev.status_code == 200
    body = ev.json()
    assert body["runs"] == []
    assert "Phase 7" in body["note"]
