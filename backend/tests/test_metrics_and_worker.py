from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.metrics import get_metrics
from app.database import create_schema
from app.main import app
from app.worker import FRSWorkerDaemon


def test_metrics_endpoint_returns_prometheus_format() -> None:
    create_schema()
    client = TestClient(app)
    metrics = get_metrics()
    metrics.inc_counter("test_counter", 1.0, test="true")
    metrics.set_gauge("test_gauge", 42.0, component="test")

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "version=0.0.4" in resp.headers.get("content-type", "")
    content = resp.text

    assert "frs_queue_depth" in content
    assert 'test_counter{test="true"} 1.0' in content
    assert 'test_gauge{component="test"} 42.0' in content


def test_liveness_and_readiness_probes() -> None:
    client = TestClient(app)
    # Liveness probe always returns 200
    live_resp = client.get("/health/live")
    assert live_resp.status_code == 200
    assert live_resp.json() == {"status": "alive"}

    # Basic health endpoint returns database and components
    health_resp = client.get("/health")
    assert health_resp.status_code in (200, 503)
    data = health_resp.json()
    assert "database" in data
    assert "model_version" in data


def test_worker_daemon_empty_queue_run_once() -> None:
    create_schema()

    class DummyPipeline:
        pass

    worker = FRSWorkerDaemon(pipeline=DummyPipeline(), poll_interval=0.01)
    processed = worker.run(once=True)
    assert processed == 0
