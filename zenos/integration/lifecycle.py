"""SystemLifecycle — Ordered startup/shutdown with circuit breakers.

Manages the full lifecycle of all ZenOS subsystems, ensuring they are
started in dependency order and shut down gracefully in reverse order.
Provides health-check aggregation and a circuit-breaker pattern that
isolates failing subsystems so the rest of the system can continue.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol

from zenos.core.events import Event, EventBus, EventType
from zenos.core.state import StateManager, SystemState

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """States of an individual circuit breaker."""

    CLOSED = "closed"       # Normal operation — requests pass through.
    OPEN = "open"           # Failing — requests are blocked.
    HALF_OPEN = "half_open" # Testing — allow one trial request.


@dataclass
class SubsystemHealth:
    """Health snapshot for a single subsystem."""

    name: str
    healthy: bool
    circuit_state: CircuitState = CircuitState.CLOSED
    last_error: Optional[str] = None
    last_check_time: float = 0.0
    consecutive_failures: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CircuitBreaker:
    """Per-subsystem circuit breaker.

    When a subsystem fails *failure_threshold* consecutive times the
    circuit opens and all operations are short-circuited.  After
    *recovery_timeout* seconds it transitions to HALF_OPEN and allows
    one trial.  If that succeeds the circuit closes again.

    Parameters
    ----------
    failure_threshold:
        Number of consecutive failures before opening the circuit.
    recovery_timeout:
        Seconds to wait before transitioning from OPEN to HALF_OPEN.
    """

    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    _state: CircuitState = CircuitState.CLOSED
    _consecutive_failures: int = 0
    _last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker transitioned to HALF_OPEN")
        return self._state

    def record_success(self) -> None:
        """Record a successful operation."""
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed operation."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()
        if self._consecutive_failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker OPEN after %d consecutive failures",
                self._consecutive_failures,
            )

    def allow_request(self) -> bool:
        """Return ``True`` if a request should be allowed through."""
        current = self.state  # triggers HALF_OPEN transition check
        return current in (CircuitState.CLOSED, CircuitState.HALF_OPEN)


class Startable(Protocol):
    """Protocol for subsystems that can be started and stopped."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health_check(self) -> bool: ...


@dataclass
class SubsystemRecord:
    """Internal record tracking a managed subsystem."""

    name: str
    instance: Any
    start_fn: Optional[Callable[..., Any]] = None
    stop_fn: Optional[Callable[..., Any]] = None
    health_fn: Optional[Callable[..., Any]] = None
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    started: bool = False
    start_time: float = 0.0


class SystemLifecycle:
    """Orchestrates the startup and shutdown of all ZenOS subsystems.

    Subsystems are started in a fixed dependency order::

        EventBus → Memory → Observability → Agent → Tools → API

    and stopped in reverse order.  Each subsystem is wrapped in a
    circuit breaker so that a failure in one module does not prevent
    the rest of the system from operating in a degraded mode.

    Parameters
    ----------
    state_manager:
        The system ``StateManager`` for tracking overall state.
    failure_threshold:
        Default circuit-breaker failure threshold for all subsystems.
    recovery_timeout:
        Default circuit-breaker recovery timeout (seconds).
    """

    # The canonical startup order — each tuple is (name, subsystem_record).
    STARTUP_ORDER: List[str] = [
        "event_bus",
        "memory",
        "observability",
        "agent",
        "tools",
        "api",
    ]

    def __init__(
        self,
        state_manager: StateManager,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        self._state_manager: StateManager = state_manager
        self._failure_threshold: int = failure_threshold
        self._recovery_timeout: float = recovery_timeout
        self._subsystems: Dict[str, SubsystemRecord] = {}
        self._event_bus: Optional[EventBus] = None
        self._startup_time: float = 0.0
        self._shutdown_time: float = 0.0

    def register_subsystem(
        self,
        name: str,
        instance: Any,
        start_fn: Optional[Callable[..., Any]] = None,
        stop_fn: Optional[Callable[..., Any]] = None,
        health_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Register a subsystem for lifecycle management.

        Parameters
        ----------
        name:
            Unique subsystem identifier (should match a name in
            ``STARTUP_ORDER``).
        instance:
            The subsystem instance.
        start_fn:
            Async or sync callable to start the subsystem.  Defaults to
            ``instance.start`` if available.
        stop_fn:
            Async or sync callable to stop the subsystem.  Defaults to
            ``instance.stop`` if available.
        health_fn:
            Async or sync callable returning ``bool``.  Defaults to
            ``instance.health_check`` if available.
        """
        if name in self._subsystems:
            logger.warning("Overwriting existing subsystem registration for '%s'", name)

        cb = CircuitBreaker(
            failure_threshold=self._failure_threshold,
            recovery_timeout=self._recovery_timeout,
        )

        resolved_start: Optional[Callable[..., Any]] = start_fn or getattr(instance, "start", None)
        resolved_stop: Optional[Callable[..., Any]] = stop_fn or getattr(instance, "stop", None)
        resolved_health: Optional[Callable[..., Any]] = health_fn or getattr(instance, "health_check", None)

        self._subsystems[name] = SubsystemRecord(
            name=name,
            instance=instance,
            start_fn=resolved_start,
            stop_fn=resolved_stop,
            health_fn=resolved_health,
            circuit_breaker=cb,
        )

        if name == "event_bus":
            self._event_bus = instance

        logger.debug("Registered subsystem '%s'", name)

    async def start_all(self) -> Dict[str, bool]:
        """Start all subsystems in the correct dependency order.

        Returns a mapping of ``name -> started_ok``.  A subsystem whose
        circuit breaker is open will be skipped and marked as unhealthy
        rather than crashing the whole startup sequence.

        Returns
        -------
        dict[str, bool]
            Start result for each subsystem.
        """
        self._state_manager.transition(SystemState.INITIALIZING)
        self._startup_time = time.monotonic()
        results: Dict[str, bool] = {}

        logger.info("Starting ZenOS subsystems…")

        # Publish SYSTEM_STARTUP
        if self._event_bus:
            try:
                await self._event_bus.publish(Event(
                    type=EventType.SYSTEM_STARTUP,
                    data={"subsystems": self.STARTUP_ORDER},
                    source="lifecycle",
                ))
            except Exception as exc:
                logger.warning("Failed to publish SYSTEM_STARTUP: %s", exc)

        for name in self.STARTUP_ORDER:
            record = self._subsystems.get(name)
            if record is None:
                logger.debug("Subsystem '%s' not registered — skipping", name)
                results[name] = False
                continue

            results[name] = await self._start_subsystem(record)

        # Determine overall state
        healthy_count = sum(1 for v in results.values() if v)
        total = len(self.STARTUP_ORDER)
        registered = sum(1 for n in self.STARTUP_ORDER if n in self._subsystems)

        if healthy_count == registered and registered > 0:
            self._state_manager.transition(SystemState.READY)
            logger.info("All %d subsystems started successfully", healthy_count)
        elif healthy_count > 0:
            self._state_manager.transition(SystemState.DEGRADED)
            logger.warning(
                "System degraded: %d/%d subsystems started",
                healthy_count,
                total,
            )
        else:
            self._state_manager.transition(SystemState.ERROR)
            logger.error("All subsystems failed to start")

        return results

    async def stop_all(self) -> Dict[str, bool]:
        """Stop all subsystems in reverse dependency order.

        Returns a mapping of ``name -> stopped_ok``.
        """
        self._state_manager.transition(SystemState.SHUTTING_DOWN)
        self._shutdown_time = time.monotonic()
        results: Dict[str, bool] = {}

        logger.info("Shutting down ZenOS subsystems…")

        # Publish SYSTEM_SHUTDOWN
        if self._event_bus:
            try:
                await self._event_bus.publish(Event(
                    type=EventType.SYSTEM_SHUTDOWN,
                    data={"subsystems": list(reversed(self.STARTUP_ORDER))},
                    source="lifecycle",
                ))
            except Exception as exc:
                logger.warning("Failed to publish SYSTEM_SHUTDOWN: %s", exc)

        for name in reversed(self.STARTUP_ORDER):
            record = self._subsystems.get(name)
            if record is None or not record.started:
                continue

            results[name] = await self._stop_subsystem(record)

        self._state_manager.transition(SystemState.STOPPED)
        logger.info("ZenOS shutdown complete")
        return results

    async def health_check_all(self) -> Dict[str, SubsystemHealth]:
        """Run health checks on all subsystems and return aggregated results.

        Subsystems whose circuit breaker is open are reported as unhealthy
        without actually invoking the health check (to avoid cascading
        failures).

        Returns
        -------
        dict[str, SubsystemHealth]
            Health status for every registered subsystem.
        """
        results: Dict[str, SubsystemHealth] = {}

        for name, record in self._subsystems.items():
            cb = record.circuit_breaker

            if not cb.allow_request():
                results[name] = SubsystemHealth(
                    name=name,
                    healthy=False,
                    circuit_state=cb.state,
                    last_error="Circuit breaker is OPEN",
                    last_check_time=time.monotonic(),
                    consecutive_failures=cb._consecutive_failures,
                )
                continue

            healthy = True
            error_msg = None

            if record.health_fn is not None:
                try:
                    result = record.health_fn()
                    if asyncio.iscoroutine(result):
                        result = await result
                    healthy = bool(result)
                except Exception as exc:
                    healthy = False
                    error_msg = str(exc)
                    logger.warning("Health check failed for '%s': %s", name, exc)

            # Update circuit breaker
            if healthy:
                cb.record_success()
            else:
                cb.record_failure()
                if error_msg is None:
                    error_msg = f"Health check returned unhealthy (failure #{cb._consecutive_failures})"

            results[name] = SubsystemHealth(
                name=name,
                healthy=healthy,
                circuit_state=cb.state,
                last_error=error_msg,
                last_check_time=time.monotonic(),
                consecutive_failures=cb._consecutive_failures,
            )

        # Publish SYSTEM_HEALTH event
        if self._event_bus:
            try:
                overall_healthy = all(h.healthy for h in results.values())
                await self._event_bus.publish(Event(
                    type=EventType.SYSTEM_HEALTH,
                    data={
                        "overall": "healthy" if overall_healthy else "degraded",
                        "subsystems": {
                            n: h.healthy for n, h in results.items()
                        },
                    },
                    source="lifecycle",
                ))
            except Exception as exc:
                logger.warning("Failed to publish SYSTEM_HEALTH: %s", exc)

        return results

    async def _start_subsystem(self, record: SubsystemRecord) -> bool:
        """Start a single subsystem with circuit-breaker protection."""
        name = record.name
        cb = record.circuit_breaker

        if not cb.allow_request():
            logger.warning(
                "Skipping '%s' — circuit breaker is OPEN (%d failures)",
                name,
                cb._consecutive_failures,
            )
            return False

        if record.start_fn is None:
            logger.warning("No start function for subsystem '%s'", name)
            return False

        logger.info("Starting subsystem '%s'…", name)
        start_time = time.monotonic()

        try:
            result = record.start_fn()
            if asyncio.iscoroutine(result):
                await result

            duration = time.monotonic() - start_time
            record.started = True
            record.start_time = duration
            cb.record_success()

            logger.info("Subsystem '%s' started in %.3fs", name, duration)
            return True

        except Exception as exc:
            duration = time.monotonic() - start_time
            cb.record_failure()
            record.started = False

            logger.error(
                "Failed to start subsystem '%s' after %.3fs: %s "
                "(circuit: %s, failures: %d)",
                name,
                duration,
                exc,
                cb.state.value,
                cb._consecutive_failures,
            )

            # Publish SYSTEM_ERROR event
            if self._event_bus:
                try:
                    await self._event_bus.publish(Event(
                        type=EventType.SYSTEM_ERROR,
                        data={
                            "subsystem": name,
                            "error": str(exc),
                            "circuit_state": cb.state.value,
                        },
                        source="lifecycle",
                        priority=2,
                    ))
                except Exception:
                    pass

            return False

    async def _stop_subsystem(self, record: SubsystemRecord) -> bool:
        """Stop a single subsystem gracefully."""
        name = record.name

        if record.stop_fn is None:
            logger.debug("No stop function for subsystem '%s'", name)
            record.started = False
            return True

        logger.info("Stopping subsystem '%s'…", name)
        start_time = time.monotonic()

        try:
            result = record.stop_fn()
            if asyncio.iscoroutine(result):
                await result

            duration = time.monotonic() - start_time
            record.started = False

            logger.info("Subsystem '%s' stopped in %.3fs", name, duration)
            return True

        except Exception as exc:
            duration = time.monotonic() - start_time
            record.started = False

            logger.error(
                "Error stopping subsystem '%s' after %.3fs: %s",
                name,
                duration,
                exc,
            )
            return False

    @property
    def uptime_seconds(self) -> float:
        """Return system uptime in seconds, or 0 if not started."""
        if self._startup_time == 0:
            return 0.0
        end = self._shutdown_time if self._shutdown_time > 0 else time.monotonic()
        return end - self._startup_time

    def __repr__(self) -> str:
        return (
            f"SystemLifecycle(subsystems={len(self._subsystems)}, "
            f"state={self._state_manager.state.value})"
        )
