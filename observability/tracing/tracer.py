"""Distributed Tracer - Span-based tracing for request flow analysis."""

from __future__ import annotations

import time
import uuid
import logging
import threading
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class SpanStatus(Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: Optional[str]
    name: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: SpanStatus = SpanStatus.OK
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    children: List['Span'] = field(default_factory=list)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, **attributes) -> None:
        self.events.append({
            'name': name,
            'timestamp': time.time(),
            'attributes': attributes,
        })

    def finish(self, status: SpanStatus = SpanStatus.OK) -> None:
        self.end_time = time.time()
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            'trace_id': self.trace_id,
            'span_id': self.span_id,
            'parent_id': self.parent_id,
            'name': self.name,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_ms': self.duration_ms,
            'status': self.status.value,
            'attributes': self.attributes,
            'events': self.events,
            'children': [c.to_dict() for c in self.children],
        }


class Tracer:
    """Thread-safe span-based tracer."""

    def __init__(self, max_traces: int = 1000):
        self._traces: Dict[str, List[Span]] = {}
        self._active_spans: Dict[str, Span] = {}
        self._max = max_traces
        self._lock = threading.Lock()

    def start_span(self, name: str, trace_id: Optional[str] = None,
                   parent_id: Optional[str] = None, **attributes) -> Span:
        span_id = str(uuid.uuid4())[:12]
        tid = trace_id or str(uuid.uuid4())[:16]
        span = Span(trace_id=tid, span_id=span_id, parent_id=parent_id, name=name)
        for k, v in attributes.items():
            span.set_attribute(k, v)
        with self._lock:
            if tid not in self._traces:
                self._traces[tid] = []
            self._traces[tid].append(span)
            self._active_spans[span_id] = span
            if parent_id and parent_id in self._active_spans:
                self._active_spans[parent_id].children.append(span)
        return span

    def end_span(self, span: Span, status: SpanStatus = SpanStatus.OK) -> None:
        span.finish(status)
        with self._lock:
            self._active_spans.pop(span.span_id, None)

    def get_trace(self, trace_id: str) -> Optional[List[Span]]:
        return self._traces.get(trace_id)

    def get_span(self, span_id: str) -> Optional[Span]:
        return self._active_spans.get(span_id)

    def get_root_spans(self, trace_id: str) -> List[Span]:
        spans = self._traces.get(trace_id, [])
        return [s for s in spans if s.parent_id is None]

    def list_traces(self, limit: int = 100) -> List[Dict[str, Any]]:
        result = []
        for tid in list(self._traces.keys())[-limit:]:
            spans = self._traces[tid]
            roots = [s for s in spans if s.parent_id is None]
            total_duration = sum(s.duration_ms or 0 for s in spans)
            has_error = any(s.status == SpanStatus.ERROR for s in spans)
            result.append({
                'trace_id': tid,
                'span_count': len(spans),
                'total_duration_ms': total_duration,
                'has_error': has_error,
                'root_span': roots[0].name if roots else None,
            })
        return result

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()
            self._active_spans.clear()
