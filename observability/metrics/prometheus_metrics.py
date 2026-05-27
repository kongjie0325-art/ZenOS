"""ZenOS Observability - 观测系统"""

from __future__ import annotations

import time
from typing import Any

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server, CollectorRegistry
except ImportError:
    Counter = Histogram = Gauge = None  # type: ignore


class PrometheusMetrics:
    """Prometheus 指标收集"""

    def __init__(self, port: int = 9090):
        self._port = port
        self._registry = None

        if Counter:
            self._registry = CollectorRegistry()
            self.task_counter = Counter(
                "zenos_tasks_total", "Total tasks", ["status"], registry=self._registry
            )
            self.tool_counter = Counter(
                "zenos_tool_calls_total", "Total tool calls", ["tool", "status"], registry=self._registry
            )
            self.token_counter = Counter(
                "zenos_tokens_total", "Total tokens used", ["model", "type"], registry=self._registry
            )
            self.task_duration = Histogram(
                "zenos_task_duration_seconds", "Task duration", ["workflow"], registry=self._registry
            )
            self.tool_duration = Histogram(
                "zenos_tool_duration_seconds", "Tool call duration", ["tool"], registry=self._registry
            )
            self.active_tasks = Gauge(
                "zenos_active_tasks", "Currently active tasks", registry=self._registry
            )
            self.memory_hits = Counter(
                "zenos_memory_hits_total", "Memory cache hits", ["layer"], registry=self._registry
            )
            self.memory_misses = Counter(
                "zenos_memory_misses_total", "Memory cache misses", ["layer"], registry=self._registry
            )

    def start(self):
        if self._registry:
            start_http_server(self._port, registry=self._registry)

    def record_task(self, status: str):
        if hasattr(self, "task_counter"):
            self.task_counter.labels(status=status).inc()

    def record_tool(self, tool: str, status: str, duration_ms: float):
        if hasattr(self, "tool_counter"):
            self.tool_counter.labels(tool=tool, status=status).inc()
        if hasattr(self, "tool_duration"):
            self.tool_duration.labels(tool=tool).observe(duration_ms / 1000)

    def record_tokens(self, model: str, token_type: str, count: int):
        if hasattr(self, "token_counter"):
            self.token_counter.labels(model=model, type=token_type).inc(count)

    def record_task_duration(self, workflow: str, duration_s: float):
        if hasattr(self, "task_duration"):
            self.task_duration.labels(workflow=workflow).observe(duration_s)

    def set_active_tasks(self, count: int):
        if hasattr(self, "active_tasks"):
            self.active_tasks.set(count)

    def record_memory_hit(self, layer: str):
        if hasattr(self, "memory_hits"):
            self.memory_hits.labels(layer=layer).inc()

    def record_memory_miss(self, layer: str):
        if hasattr(self, "memory_misses"):
            self.memory_misses.labels(layer=layer).inc()


class StructuredLogger:
    """结构化日志"""

    def __init__(self, service: str = "zenos"):
        self._service = service
        try:
            import structlog
            self._logger = structlog.get_logger(service)
        except ImportError:
            self._logger = None

    def info(self, event: str, **kwargs: Any):
        if self._logger:
            self._logger.info(event, **kwargs)
        else:
            print(f"[INFO] {self._service}: {event} {kwargs}")

    def error(self, event: str, **kwargs: Any):
        if self._logger:
            self._logger.error(event, **kwargs)
        else:
            print(f"[ERROR] {self._service}: {event} {kwargs}")

    def warning(self, event: str, **kwargs: Any):
        if self._logger:
            self._logger.warning(event, **kwargs)
        else:
            print(f"[WARN] {self._service}: {event} {kwargs}")

    def debug(self, event: str, **kwargs: Any):
        if self._logger:
            self._logger.debug(event, **kwargs)
        else:
            print(f"[DEBUG] {self._service}: {event} {kwargs}")
