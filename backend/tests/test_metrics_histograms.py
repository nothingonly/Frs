from __future__ import annotations

from app.core.metrics import MetricsRegistry


def test_histogram_metrics_observation_and_render() -> None:
    registry = MetricsRegistry()
    registry.observe_histogram("frs_batch_processing_duration_seconds", 0.045, stage="recognition")
    registry.observe_histogram("frs_batch_processing_duration_seconds", 0.120, stage="recognition")
    registry.observe_histogram("frs_batch_processing_duration_seconds", 2.500, stage="recognition")

    rendered = registry.render()

    assert "# TYPE frs_batch_processing_duration_seconds histogram" in rendered
    assert 'frs_batch_processing_duration_seconds_bucket{le="0.05",stage="recognition"} 1.0' in rendered
    assert 'frs_batch_processing_duration_seconds_bucket{le="0.25",stage="recognition"} 2.0' in rendered
    assert 'frs_batch_processing_duration_seconds_bucket{le="+Inf",stage="recognition"} 3.0' in rendered
    assert 'frs_batch_processing_duration_seconds_count{stage="recognition"} 3.0' in rendered
    assert "frs_batch_processing_duration_seconds_sum" in rendered
