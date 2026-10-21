from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from app.database import SessionLocal
from app.db.entities import CaptureBatchJob


class MetricsRegistry:
    """Thread-safe, lightweight in-process metrics collector in Prometheus exposition format."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(lambda: defaultdict(float))
        self._gauges: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(lambda: defaultdict(float))
        self._histograms: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "buckets": (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            "entries": defaultdict(lambda: {"counts": defaultdict(float), "sum": 0.0, "count": 0.0}),
        })
        known_statuses = {"QUEUED", "PROCESSING", "SUCCEEDED", "FAILED", "REJECTED", "DEAD_LETTER"}
        for s in sorted(known_statuses):
            self.set_gauge("frs_queue_depth", 0.0, status=s)

    def inc_counter(self, name: str, value: float = 1.0, **labels: str) -> None:
        label_key = tuple(sorted(labels.items()))
        with self._lock:
            self._counters[name][label_key] += value

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        label_key = tuple(sorted(labels.items()))
        with self._lock:
            self._gauges[name][label_key] = value

    def observe_histogram(
        self,
        name: str,
        value: float,
        buckets: tuple[float, ...] = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        **labels: str,
    ) -> None:
        label_key = tuple(sorted(labels.items()))
        with self._lock:
            hist = self._histograms[name]
            hist["buckets"] = buckets
            entry = hist["entries"][label_key]
            entry["sum"] += value
            entry["count"] += 1.0
            for b in buckets:
                if value <= b:
                    entry["counts"][b] += 1.0

    def _render_labels(self, labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        items = [f'{k}="{v}"' for k, v in labels]
        return "{" + ",".join(items) + "}"

    def render(self) -> str:
        lines: list[str] = []

        # 1. Dynamic database queue depth gauge
        try:
            with SessionLocal() as db:
                counts = db.execute(
                    select(CaptureBatchJob.status, func.count(CaptureBatchJob.batch_id))
                    .group_by(CaptureBatchJob.status)
                ).all()
                known_statuses = {"QUEUED", "PROCESSING", "SUCCEEDED", "FAILED", "REJECTED", "DEAD_LETTER"}
                counts_dict = {status: count for status, count in counts}
                for s in sorted(known_statuses):
                    self.set_gauge("frs_queue_depth", float(counts_dict.get(s, 0)), status=s)
        except Exception:
            pass

        # 2. Render gauges
        with self._lock:
            for name, entries in sorted(self._gauges.items()):
                lines.append(f"# HELP {name} Current gauge value for {name}")
                lines.append(f"# TYPE {name} gauge")
                for labels, val in sorted(entries.items()):
                    lines.append(f"{name}{self._render_labels(labels)} {val}")

            # 3. Render counters
            for name, entries in sorted(self._counters.items()):
                lines.append(f"# HELP {name} Total count of {name}")
                lines.append(f"# TYPE {name} counter")
                for labels, val in sorted(entries.items()):
                    lines.append(f"{name}{self._render_labels(labels)} {val}")

            # 4. Render histograms
            for name, hist in sorted(self._histograms.items()):
                lines.append(f"# HELP {name} Histogram observation for {name}")
                lines.append(f"# TYPE {name} histogram")
                buckets = sorted(hist["buckets"])
                for label_key, entry in sorted(hist["entries"].items()):
                    for b in buckets:
                        b_labels = dict(label_key)
                        b_labels["le"] = str(b)
                        lines.append(f"{name}_bucket{self._render_labels(tuple(sorted(b_labels.items())))} {entry['counts'][b]}")
                    inf_labels = dict(label_key)
                    inf_labels["le"] = "+Inf"
                    lines.append(f"{name}_bucket{self._render_labels(tuple(sorted(inf_labels.items())))} {entry['count']}")
                    lines.append(f"{name}_sum{self._render_labels(label_key)} {entry['sum']}")
                    lines.append(f"{name}_count{self._render_labels(label_key)} {entry['count']}")

        return "\n".join(lines) + "\n"


_global_metrics = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    return _global_metrics
