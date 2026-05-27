"""AutoScaler - Monitors system metrics and auto-adjusts resource allocation.

Monitors: cache hit rate, memory usage, event queue depth, tool error rate
Adjusts: cache size, worker count, batch sizes, compression frequency
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ScalingPolicy:
    """Defines when and how to scale a resource."""
    resource: str           # cache_size | worker_count | batch_size | compression_freq
    scale_up_threshold: float   # metric value that triggers scale up
    scale_down_threshold: float # metric value that triggers scale down
    scale_up_factor: float = 1.5
    scale_down_factor: float = 0.75
    min_value: float = 1.0
    max_value: float = 1000.0
    cooldown_seconds: float = 60.0
    last_scaled: float = 0.0

    def can_scale(self) -> bool:
        return time.time() - self.last_scaled >= self.cooldown_seconds


@dataclass
class ScalingEvent:
    """Record of a scaling action."""
    timestamp: float
    resource: str
    direction: str  # up | down
    old_value: float
    new_value: float
    reason: str


class AutoScaler:
    """Monitors system metrics and auto-adjusts resources."""

    def __init__(self, event_bus: Any = None):
        self._event_bus = event_bus
        self._policies: Dict[str, ScalingPolicy] = {}
        self._current_values: Dict[str, float] = {}
        self._history: List[ScalingEvent] = []
        self._setup_default_policies()

    def _setup_default_policies(self) -> None:
        """Configure default scaling policies."""
        self._policies["cache_size"] = ScalingPolicy(
            resource="cache_size",
            scale_up_threshold=0.7,    # scale up when usage > 70%
            scale_down_threshold=0.3,  # scale down when usage < 30%
            min_value=10,
            max_value=10000,
        )
        self._policies["worker_count"] = ScalingPolicy(
            resource="worker_count",
            scale_up_threshold=0.8,
            scale_down_threshold=0.2,
            min_value=1,
            max_value=16,
        )
        self._policies["compression_freq"] = ScalingPolicy(
            resource="compression_freq",
            scale_up_threshold=0.85,   # compress more when memory > 85%
            scale_down_threshold=0.5,
            min_value=0.1,
            max_value=1.0,
        )

        # Initialize current values
        self._current_values["cache_size"] = 100
        self._current_values["worker_count"] = 4
        self._current_values["compression_freq"] = 0.8

    # ── Evaluation ──────────────────────────────────────────────────

    def evaluate(self, metrics: Dict[str, float]) -> List[ScalingEvent]:
        """Evaluate all policies against current metrics. Returns scaling events."""
        events = []

        # Map metric names to resources
        metric_resource_map = {
            "cache_usage_ratio": "cache_size",
            "worker_usage_ratio": "worker_count",
            "memory_usage_ratio": "compression_freq",
        }

        for metric_name, value in metrics.items():
            resource = metric_resource_map.get(metric_name)
            if resource is None:
                continue

            policy = self._policies.get(resource)
            if policy is None or not policy.can_scale():
                continue

            current = self._current_values.get(resource, 0)

            if value >= policy.scale_up_threshold:
                new_value = min(policy.max_value, current * policy.scale_up_factor)
                if new_value != current:
                    event = self._apply_scaling(resource, new_value, f"{metric_name}={value:.2f} > {policy.scale_up_threshold}")
                    events.append(event)

            elif value <= policy.scale_down_threshold:
                new_value = max(policy.min_value, current * policy.scale_down_factor)
                if new_value != current:
                    event = self._apply_scaling(resource, new_value, f"{metric_name}={value:.2f} < {policy.scale_down_threshold}")
                    events.append(event)

        return events

    def _apply_scaling(self, resource: str, new_value: float, reason: str) -> ScalingEvent:
        old_value = self._current_values.get(resource, 0)
        self._current_values[resource] = new_value
        self._policies[resource].last_scaled = time.time()

        direction = "up" if new_value > old_value else "down"
        event = ScalingEvent(
            timestamp=time.time(),
            resource=resource,
            direction=direction,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )
        self._history.append(event)
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

        logger.info("AutoScale: %s %s %.0f → %.0f (%s)",
                    resource, direction, old_value, new_value, reason)

        # Emit event
        if self._event_bus is not None:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._emit_scaling_event(event))
            except RuntimeError:
                pass

        return event

    async def _emit_scaling_event(self, event: ScalingEvent) -> None:
        try:
            from core.events import Event, EventType
            await self._event_bus.publish(Event(
                type=EventType.SYSTEM_HEALTH,
                data={
                    'scaling': event.resource,
                    'direction': event.direction,
                    'old': event.old_value,
                    'new': event.new_value,
                },
                source="auto_scaler",
            ))
        except Exception:
            pass

    # ── Recommendations ────────────────────────────────────────────

    def get_recommendations(self) -> List[Dict[str, str]]:
        """Get human-readable scaling recommendations."""
        recommendations = []
        for resource, policy in self._policies.items():
            current = self._current_values.get(resource, 0)
            utilization = current / policy.max_value if policy.max_value > 0 else 0

            if utilization > 0.8:
                recommendations.append({
                    'resource': resource,
                    'action': 'scale_up',
                    'current': str(int(current)),
                    'recommended': str(int(min(policy.max_value, current * 1.5))),
                    'reason': f'High utilization ({utilization:.0%})',
                })
            elif utilization < 0.2 and current > policy.min_value:
                recommendations.append({
                    'resource': resource,
                    'action': 'scale_down',
                    'current': str(int(current)),
                    'recommended': str(int(max(policy.min_value, current * 0.75))),
                    'reason': f'Low utilization ({utilization:.0%})',
                })
        return recommendations

    def get_scaling_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [
            {
                'timestamp': e.timestamp,
                'resource': e.resource,
                'direction': e.direction,
                'old': e.old_value,
                'new': e.new_value,
                'reason': e.reason,
            }
            for e in self._history[-limit:]
        ]

    def get_current_values(self) -> Dict[str, float]:
        return dict(self._current_values)
