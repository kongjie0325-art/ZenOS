"""Event Bus - Async publish/subscribe for inter-module communication.

Supports typed events, wildcard subscriptions, priority handlers,
and event history for replay/debugging.
"""

from __future__ import annotations

import asyncio
import time
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


class EventType(Enum):
    # System lifecycle
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"
    SYSTEM_HEALTH = "system.health"

    # Agent lifecycle
    AGENT_START = "agent.start"
    AGENT_THINK = "agent.think"
    AGENT_ACT = "agent.act"
    AGENT_OBSERVE = "agent.observe"
    AGENT_REFLECT = "agent.reflect"
    AGENT_COMPLETE = "agent.complete"
    AGENT_ERROR = "agent.error"

    # Tool execution
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    TOOL_ERROR = "tool.error"

    # Memory operations
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_COMPRESS = "memory.compress"
    MEMORY_EVICT = "memory.evict"

    # Plugin
    PLUGIN_LOAD = "plugin.load"
    PLUGIN_UNLOAD = "plugin.unload"
    PLUGIN_ERROR = "plugin.error"

    # User interaction
    USER_MESSAGE = "user.message"
    USER_FEEDBACK = "user.feedback"

    # Observability
    METRIC_RECORD = "metric.record"
    TRACE_SPAN = "trace.span"
    ALERT_TRIGGER = "alert.trigger"


@dataclass
class Event:
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    id: str = ""
    correlation_id: str = ""
    priority: int = 0  # higher = more urgent

    def __post_init__(self):
        if not self.id:
            import uuid
            self.id = str(uuid.uuid4())[:12]


Handler = Callable[[Event], Any]


class EventBus:
    """Async event bus with priority routing and history."""

    def __init__(self, max_history: int = 10000):
        self._handlers: Dict[EventType, List[tuple]] = defaultdict(list)
        self._wildcards: List[tuple] = []  # handlers for all events
        self._history: List[Event] = []
        self._max_history = max_history
        self._event_queue: asyncio.Queue = None
        self._running = False
        self._lock = asyncio.Lock()
        self._stats: Dict[str, int] = defaultdict(int)

    async def start(self):
        self._event_queue = asyncio.Queue()
        self._running = True
        asyncio.create_task(self._dispatch_loop())
        logger.info("EventBus started")

    async def stop(self):
        self._running = False
        # Drain remaining events
        while not self._event_queue.empty():
            await asyncio.sleep(0.01)
        logger.info("EventBus stopped")

    def subscribe(self, event_type: EventType, handler: Handler, priority: int = 0) -> None:
        self._handlers[event_type].append((priority, handler))
        self._handlers[event_type].sort(key=lambda x: -x[0])

    def subscribe_all(self, handler: Handler, priority: int = 0) -> None:
        self._wildcards.append((priority, handler))
        self._wildcards.sort(key=lambda x: -x[0])

    def unsubscribe(self, event_type: EventType, handler: Handler) -> None:
        self._handlers[event_type] = [
            (p, h) for p, h in self._handlers[event_type] if h is not handler
        ]

    async def publish(self, event: Event) -> None:
        await self._event_queue.put(event)
        self._stats['published'] += 1

    async def publish_and_wait(self, event: Event, timeout: float = 30.0) -> List[Any]:
        """Publish and wait for all handlers to complete."""
        results = []
        handlers = self._handlers.get(event.type, []) + self._wildcards
        for priority, handler in sorted(handlers, key=lambda x: -x[0]):
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await asyncio.wait_for(handler(event), timeout=timeout)
                else:
                    result = handler(event)
                results.append(result)
            except Exception as e:
                logger.error(f"Handler error for {event.type}: {e}")
                results.append(e)
        return results

    async def _dispatch_loop(self):
        while self._running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.5)
                async with self._lock:
                    self._history.append(event)
                    if len(self._history) > self._max_history:
                        self._history = self._history[-self._max_history:]

                handlers = self._handlers.get(event.type, []) + self._wildcards
                for priority, handler in handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event)
                        else:
                            handler(event)
                    except Exception as e:
                        logger.error(f"Dispatch error for {event.type}: {e}")
                self._stats['dispatched'] += 1
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Dispatch loop error: {e}")

    def get_history(self, event_type: Optional[EventType] = None, limit: int = 100) -> List[Event]:
        events = self._history
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]

    def get_stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def clear_history(self):
        self._history.clear()
