"""Metrics Collector - In-memory metrics with counters, gauges, histograms."""

from __future__ import annotations

import threading
import time
import logging
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class Metric:
    name: str
    type: MetricType
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    description: str = ""
    unit: str = ""


@dataclass
class HistogramBucket:
    upper_bound: float
    count: int = 0


class MetricsCollector:
    """Thread-safe in-memory metrics collection."""

    def __init__(self, max_metrics: int = 10000):
        self._metrics: Dict[str, Metric] = {}
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._max = max_metrics
        self._lock = threading.Lock()

    def counter(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None,
                description: str = "") -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value
            self._metrics[key] = Metric(
                name=name, type=MetricType.COUNTER,
                value=self._counters[key], labels=labels or {},
                description=description,
            )

    def gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None,
              description: str = "") -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value
            self._metrics[key] = Metric(
                name=name, type=MetricType.GAUGE,
                value=value, labels=labels or {},
                description=description,
            )

    def histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None,
                  description: str = "") -> None:
        key = self._key(name, labels)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)
            data = self._histograms[key]
            self._metrics[key] = Metric(
                name=name, type=MetricType.HISTOGRAM,
                value=sum(data) / len(data) if data else 0,
                labels=labels or {},
                description=description,
            )

    def get(self, name: str, labels: Optional[Dict[str, str]] = None) -> Optional[Metric]:
        key = self._key(name, labels)
        return self._metrics.get(key)

    def get_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        key = self._key(name, labels)
        return self._counters.get(key, 0.0)

    def get_gauge(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        key = self._key(name, labels)
        return self._gauges.get(key, 0.0)

    def get_histogram_stats(self, name: str, labels: Optional[Dict[str, str]] = None) -> Dict[str, float]:
        key = self._key(name, labels)
        data = self._histograms.get(key, [])
        if not data:
            return {'count': 0, 'sum': 0, 'avg': 0, 'min': 0, 'max': 0, 'p50': 0, 'p95': 0, 'p99': 0}
        sorted_data = sorted(data)
        n = len(sorted_data)
        return {
            'count': n,
            'sum': sum(sorted_data),
            'avg': sum(sorted_data) / n,
            'min': sorted_data[0],
            'max': sorted_data[-1],
            'p50': sorted_data[int(n * 0.5)],
            'p95': sorted_data[int(n * 0.95)],
            'p99': sorted_data[int(n * 0.99)],
        }

    def list_all(self) -> List[Metric]:
        return list(self._metrics.values())

    def reset(self, name: Optional[str] = None) -> None:
        with self._lock:
            if name:
                keys_to_remove = [k for k in self._metrics if self._metrics[k].name == name]
                for k in keys_to_remove:
                    del self._metrics[k]
                    self._counters.pop(k, None)
                    self._gauges.pop(k, None)
                    self._histograms.pop(k, None)
            else:
                self._metrics.clear()
                self._counters.clear()
                self._gauges.clear()
                self._histograms.clear()

    def export_prometheus(self) -> str:
        """Export in Prometheus text format."""
        lines = []
        for metric in self._metrics.values():
            name = metric.name
            labels_str = ""
            if metric.labels:
                label_pairs = ",".join(f'{k}="{v}"' for k, v in metric.labels.items())
                labels_str = "{" + label_pairs + "}"
            lines.append(f"{name}{labels_str} {metric.value}")
        return "\n".join(lines)

    def _key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}[{label_str}]"
