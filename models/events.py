"""Event data models."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EventModel:
    id: str
    type: str
    source: str
    timestamp: str
    data: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    priority: int = 0


@dataclass
class EventBatch:
    events: List[EventModel] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100


@dataclass
class EventFilter:
    event_types: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    correlation_id: str = ""
    since: str = ""
    until: str = ""
    min_priority: int = 0
    limit: int = 100
