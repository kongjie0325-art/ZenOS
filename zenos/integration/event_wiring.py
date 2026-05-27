"""EventWiring - Connects all subsystems through the EventBus.

Subscribes observability, memory, and alerting modules to relevant events,
creating a fully event-driven architecture where every action is tracked,
measured, and can trigger downstream effects.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class EventWiring:
    """Wires all subsystems together through EventBus subscriptions.

    Subscriptions:
    - All events → MetricsCollector (counters per event type)
    - AGENT_* events → Tracer (spans for agent lifecycle)
    - MEMORY_* events → MemoryBridge (auto-compression trigger)
    - SYSTEM_ERROR → AlertManager (immediate alert)
    - TOOL_ERROR → SelfHealingEngine (recovery trigger)
    """

    def __init__(
        self,
        event_bus: Any,
        metrics: Any = None,
        tracer: Any = None,
        alerter: Any = None,
        memory_bridge: Any = None,
    ):
        self._bus = event_bus
        self._metrics = metrics
        self._tracer = tracer
        self._alerter = alerter
        self._memory = memory_bridge
        self._active_spans: Dict[str, Any] = {}
        self._wired = False

    def wire_all(self) -> None:
        """Subscribe all handlers to the EventBus."""
        if self._wired:
            return

        from zenos.core.events import EventType as ET

        # ── All events → Metrics ──────────────────────────────────
        if self._metrics is not None:
            self._bus.subscribe_all(self._count_event, priority=0)
            logger.info("Wired: all events → MetricsCollector")

        # ── Agent events → Tracing ────────────────────────────────
        if self._tracer is not None:
            self._bus.subscribe(ET.AGENT_START, self._start_agent_span)
            self._bus.subscribe(ET.AGENT_THINK, self._record_think)
            self._bus.subscribe(ET.AGENT_ACT, self._record_act)
            self._bus.subscribe(ET.AGENT_OBSERVE, self._record_observe)
            self._bus.subscribe(ET.AGENT_COMPLETE, self._end_agent_span)
            self._bus.subscribe(ET.AGENT_ERROR, self._end_agent_span_error)
            logger.info("Wired: AGENT_* → Tracer")

        # ── Memory events → MemoryBridge ──────────────────────────
        if self._memory is not None:
            self._bus.subscribe(ET.MEMORY_WRITE, self._check_compression)
            logger.info("Wired: MEMORY_WRITE → MemoryBridge")

        # ── Error events → Alerting ───────────────────────────────
        if self._alerter is not None:
            self._bus.subscribe(ET.SYSTEM_ERROR, self._alert_on_error)
            self._bus.subscribe(ET.AGENT_ERROR, self._alert_on_error)
            self._bus.subscribe(ET.TOOL_ERROR, self._alert_on_error)
            logger.info("Wired: ERROR events → AlertManager")

        # ── Tool events → Metrics ─────────────────────────────────
        if self._metrics is not None:
            self._bus.subscribe(ET.TOOL_CALL, self._count_tool_call)
            self._bus.subscribe(ET.TOOL_RESULT, self._count_tool_result)
            self._bus.subscribe(ET.TOOL_ERROR, self._count_tool_error)
            logger.info("Wired: TOOL_* → MetricsCollector")

        self._wired = True
        logger.info("EventWiring complete: all subsystems connected")

    # ── Metrics handlers ───────────────────────────────────────────

    def _count_event(self, event) -> None:
        try:
            self._metrics.counter("zenos.events_total", 1, {"type": event.type.value})
        except Exception:
            pass

    def _count_tool_call(self, event) -> None:
        try:
            tool = event.data.get("tool", "unknown")
            self._metrics.counter("zenos.tool_calls_total", 1, {"tool": tool})
        except Exception:
            pass

    def _count_tool_result(self, event) -> None:
        try:
            tool = event.data.get("tool", "unknown")
            self._metrics.counter("zenos.tool_results_total", 1, {"tool": tool})
        except Exception:
            pass

    def _count_tool_error(self, event) -> None:
        try:
            tool = event.data.get("tool", "unknown")
            self._metrics.counter("zenos.tool_errors_total", 1, {"tool": tool})
        except Exception:
            pass

    # ── Tracing handlers ──────────────────────────────────────────

    def _start_agent_span(self, event) -> None:
        try:
            goal = event.data.get("goal", "")
            span = self._tracer.start_span("agent.run", goal=goal, agent_id=event.data.get("agent_id", ""))
            trace_id = span.trace_id
            self._active_spans[trace_id] = span
            # Store trace_id in event correlation
            if not event.correlation_id:
                event.correlation_id = trace_id
        except Exception:
            pass

    def _record_think(self, event) -> None:
        try:
            trace_id = event.correlation_id
            if trace_id and trace_id in self._active_spans:
                span = self._tracer.get_span(trace_id)
                if span:
                    span.add_event("thought", content=event.data.get("thought", "")[:200])
        except Exception:
            pass

    def _record_act(self, event) -> None:
        try:
            trace_id = event.correlation_id
            if trace_id and trace_id in self._active_spans:
                span = self._tracer.get_span(trace_id)
                if span:
                    span.add_event("action", tool=event.data.get("tool", ""))
                    self._metrics.histogram("zenos.agent.action_duration", event.data.get("duration", 0))
        except Exception:
            pass

    def _record_observe(self, event) -> None:
        try:
            trace_id = event.correlation_id
            if trace_id and trace_id in self._active_spans:
                span = self._tracer.get_span(trace_id)
                if span:
                    span.add_event("observation", content=event.data.get("observation", "")[:200])
        except Exception:
            pass

    def _end_agent_span(self, event) -> None:
        try:
            trace_id = event.correlation_id
            if trace_id and trace_id in self._active_spans:
                span = self._active_spans.pop(trace_id)
                self._tracer.end_span(span)
        except Exception:
            pass

    def _end_agent_span_error(self, event) -> None:
        try:
            trace_id = event.correlation_id
            if trace_id and trace_id in self._active_spans:
                span = self._active_spans.pop(trace_id)
                from zenos.observability.tracing.tracer import SpanStatus
                self._tracer.end_span(span, SpanStatus.ERROR)
        except Exception:
            pass

    # ── Memory compression handler ─────────────────────────────────

    def _check_compression(self, event) -> None:
        """Auto-trigger compression when memory write frequency is high."""
        if self._memory is None:
            return
        try:
            # Check every 10 writes
            import random
            if random.random() < 0.1:  # 10% chance per write
                self._memory.check_and_compress()
        except Exception:
            pass

    # ── Alert handler ──────────────────────────────────────────────

    def _alert_on_error(self, event) -> None:
        if self._alerter is None:
            return
        try:
            error_data = {
                "type": event.type.value,
                "source": event.source,
                "error": event.data.get("error", ""),
                "timestamp": event.timestamp,
            }
            self._alerter.evaluate(error_data)
        except Exception:
            pass
