"""Audit Logger - Immutable audit trail for security events."""

from __future__ import annotations

import json
import time
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AuditEvent:
    id: str
    timestamp: float
    action: str
    actor: str
    resource: str
    result: str  # success | failure | denied
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: str = ""
    user_agent: str = ""


class AuditLogger:
    """Thread-safe audit logger with file persistence."""

    def __init__(self, log_file: Optional[str] = None, max_memory_events: int = 10000):
        self._events: List[AuditEvent] = []
        self._log_file = log_file
        self._max = max_memory_events
        self._lock = threading.Lock()
        self._counter = 0

    def log(self, action: str, actor: str, resource: str, result: str = "success",
            details: Optional[Dict[str, Any]] = None, **kwargs) -> AuditEvent:
        with self._lock:
            self._counter += 1
            event = AuditEvent(
                id=f"audit-{self._counter:08d}",
                timestamp=time.time(),
                action=action,
                actor=actor,
                resource=resource,
                result=result,
                details=details or {},
                **kwargs,
            )
            self._events.append(event)
            if len(self._events) > self._max:
                self._events = self._events[-self._max:]
        # Write to file outside lock
        if self._log_file:
            self._append_to_file(event)
        return event

    def query(self, action: Optional[str] = None, actor: Optional[str] = None,
              resource: Optional[str] = None, result: Optional[str] = None,
              since: Optional[float] = None, until: Optional[float] = None,
              limit: int = 100) -> List[AuditEvent]:
        with self._lock:
            events = self._events
            if action:
                events = [e for e in events if e.action == action]
            if actor:
                events = [e for e in events if e.actor == actor]
            if resource:
                events = [e for e in events if e.resource == resource]
            if result:
                events = [e for e in events if e.result == result]
            if since:
                events = [e for e in events if e.timestamp >= since]
            if until:
                events = [e for e in events if e.timestamp <= until]
            return events[-limit:]

    def get_recent(self, limit: int = 50) -> List[AuditEvent]:
        return self._events[-limit:]

    def count(self, action: Optional[str] = None) -> int:
        if action:
            return sum(1 for e in self._events if e.action == action)
        return len(self._events)

    def export_json(self, path: str) -> int:
        events = [self._event_to_dict(e) for e in self._events]
        Path(path).write_text(json.dumps(events, indent=2, default=str))
        return len(events)

    def _append_to_file(self, event: AuditEvent) -> None:
        try:
            with open(self._log_file, 'a') as f:
                f.write(json.dumps(self._event_to_dict(event), default=str) + "\n")
        except Exception as e:
            logger.error(f"Audit file write error: {e}")

    @staticmethod
    def _event_to_dict(event: AuditEvent) -> Dict[str, Any]:
        return {
            'id': event.id,
            'timestamp': event.timestamp,
            'action': event.action,
            'actor': event.actor,
            'resource': event.resource,
            'result': event.result,
            'details': event.details,
            'ip_address': event.ip_address,
            'user_agent': event.user_agent,
        }
