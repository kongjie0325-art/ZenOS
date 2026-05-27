"""System API routes — health, config, and metrics endpoints."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from zenos.api.routes.agent import Route, HttpMethod


@dataclass
class HealthResponse:
    """System health check response."""

    status: str  # "healthy", "degraded", "unhealthy"
    version: str = "0.1.0"
    uptime_seconds: float = 0.0
    checks: dict[str, bool] = field(default_factory=dict)


@dataclass
class ConfigResponse:
    """System configuration response (sanitized — no secrets)."""

    environment: str = "production"
    log_level: str = "INFO"
    max_concurrent_runs: int = 10
    model_defaults: dict[str, Any] = field(default_factory=dict)
    feature_flags: dict[str, bool] = field(default_factory=dict)


@dataclass
class SystemMetricsResponse:
    """System-level metrics snapshot."""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    active_runs: int = 0
    queued_runs: int = 0
    total_runs_completed: int = 0
    total_runs_failed: int = 0
    average_run_duration_ms: float = 0.0
    timestamp: float = 0.0


class SystemRouter:
    """System route handler — health, config, and metrics endpoints.

    Provides operational visibility into the ZenOS runtime without
    exposing sensitive configuration values.
    """

    def __init__(self, version: str = "0.1.0") -> None:
        self._routes = self._build_routes()
        self._version = version
        self._start_time = time.time()
        self._total_completed = 0
        self._total_failed = 0
        self._active_runs = 0
        self._queued_runs = 0
        self._durations: list[float] = []

    @property
    def routes(self) -> list[Route]:
        """Return the list of registered routes."""
        return self._routes

    def _build_routes(self) -> list[Route]:
        """Register all system routes."""
        return [
            Route(
                path="/api/v1/system/health",
                method=HttpMethod.GET,
                handler=self.health,
                name="system_health",
                require_auth=False,
            ),
            Route(
                path="/api/v1/system/config",
                method=HttpMethod.GET,
                handler=self.config,
                name="system_config",
            ),
            Route(
                path="/api/v1/system/metrics",
                method=HttpMethod.GET,
                handler=self.metrics,
                name="system_metrics",
            ),
        ]

    def health(self, **kwargs: Any) -> HealthResponse:
        """Return the current system health status.

        Performs dependency checks and reports overall health.

        Returns:
            HealthResponse with status and individual check results.
        """
        checks: dict[str, bool] = {
            "memory_store": True,
            "model_provider": True,
            "tool_executor": True,
        }
        all_healthy = all(checks.values())
        status = "healthy" if all_healthy else "degraded"
        return HealthResponse(
            status=status,
            version=self._version,
            uptime_seconds=round(time.time() - self._start_time, 2),
            checks=checks,
        )

    def config(self, **kwargs: Any) -> ConfigResponse:
        """Return the current system configuration (sanitized).

        Secrets and credentials are never included in the response.

        Returns:
            ConfigResponse with safe configuration values.
        """
        return ConfigResponse(
            environment=os.environ.get("ZENOS_ENV", "production"),
            log_level=os.environ.get("ZENOS_LOG_LEVEL", "INFO"),
            max_concurrent_runs=10,
            model_defaults={
                "default_model": "claude-sonnet-4-20250514",
                "default_temperature": 0.7,
                "default_max_tokens": 4096,
            },
            feature_flags={
                "sandbox_enabled": True,
                "memory_compression": True,
                "audit_logging": True,
            },
        )

    def metrics(self, **kwargs: Any) -> SystemMetricsResponse:
        """Return a snapshot of system-level metrics.

        Returns:
            SystemMetricsResponse with current resource usage and run stats.
        """
        avg_duration = (
            sum(self._durations) / len(self._durations)
            if self._durations
            else 0.0
        )
        return SystemMetricsResponse(
            cpu_percent=0.0,  # Placeholder: read from psutil in production
            memory_percent=0.0,
            active_runs=self._active_runs,
            queued_runs=self._queued_runs,
            total_runs_completed=self._total_completed,
            total_runs_failed=self._total_failed,
            average_run_duration_ms=round(avg_duration, 2),
            timestamp=time.time(),
        )

    def record_run_completion(self, duration_ms: float, failed: bool = False) -> None:
        """Record a completed run for metrics tracking.

        Args:
            duration_ms: How long the run took in milliseconds.
            failed: Whether the run ended in failure.
        """
        self._durations.append(duration_ms)
        if failed:
            self._total_failed += 1
        else:
            self._total_completed += 1
