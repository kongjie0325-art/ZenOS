"""Memory data models."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryEntryModel:
    id: str
    content: str
    memory_type: str = "working"  # working | episodic | semantic | procedural
    importance: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MemorySearchRequest:
    query: str
    memory_types: List[str] = field(default_factory=lambda: ["working", "episodic", "semantic"])
    limit: int = 10
    min_score: float = 0.0
    strategy: str = "hybrid"  # keyword | semantic | temporal | hybrid
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemorySearchResponse:
    results: List[MemoryEntryModel] = field(default_factory=list)
    total: int = 0
    query_time_ms: float = 0.0
    strategy_used: str = ""


@dataclass
class MemoryAddRequest:
    content: str
    memory_type: str = "working"
    importance: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryCompressRequest:
    memory_type: str = "working"
    threshold: float = 0.8
    keep_last_n: int = 10


@dataclass
class MemoryCompressResponse:
    compressed_count: int = 0
    remaining_count: int = 0
    summary: str = ""
    space_saved_pct: float = 0.0
