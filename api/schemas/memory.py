"""Memory request and response schemas for the ZenOS API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MemorySearchRequest:
    """Request to search memory entries.

    Attributes:
        query: The search query string.
        limit: Maximum number of results to return.
        min_score: Minimum relevance score threshold (0.0 – 1.0).
        filters: Key-value filters to narrow results.
    """

    query: str
    limit: int = 10
    min_score: float = 0.0
    filters: dict[str, str] = field(default_factory=dict)


@dataclass
class MemorySearchResult:
    """A single memory search result.

    Attributes:
        id: Unique memory entry identifier.
        content: The stored memory content.
        score: Relevance score (0.0 – 1.0).
        created_at: Unix timestamp when the entry was created.
        metadata: Additional metadata attached to the entry.
    """

    id: str
    content: str
    score: float
    created_at: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class MemorySearchResponse:
    """Response from a memory search.

    Attributes:
        results: List of matching memory entries.
        total: Total number of matches.
        query_time_ms: Time taken to execute the search.
    """

    results: list[MemorySearchResult] = field(default_factory=list)
    total: int = 0
    query_time_ms: float = 0.0


@dataclass
class MemoryAddRequest:
    """Request to add a new memory entry.

    Attributes:
        content: The memory content to store.
        tags: Tags for categorization.
        metadata: Additional metadata key-value pairs.
    """

    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class MemoryAddResponse:
    """Response from adding a memory entry.

    Attributes:
        id: Unique identifier of the new entry.
        status: Operation status ("created").
        created_at: Unix timestamp when the entry was created.
    """

    id: str
    status: str = "created"
    created_at: float = 0.0


@dataclass
class MemoryDeleteResponse:
    """Response from deleting a memory entry.

    Attributes:
        id: Unique identifier of the deleted entry.
        status: Operation status ("deleted" or "not_found").
        deleted: Whether the entry was actually deleted.
    """

    id: str
    status: str = "deleted"
    deleted: bool = True


@dataclass
class MemoryCompressRequest:
    """Request to compress memory entries.

    Attributes:
        strategy: Compression strategy — "summarize", "deduplicate", or "prune".
        older_than_days: Only compress entries older than this many days.
        max_entries: Maximum number of entries to retain after compression.
    """

    strategy: str = "summarize"
    older_than_days: Optional[int] = None
    max_entries: Optional[int] = None


@dataclass
class MemoryCompressResponse:
    """Response from memory compression.

    Attributes:
        entries_before: Number of entries before compression.
        entries_after: Number of entries after compression.
        removed: Number of entries removed.
        duration_ms: Time taken to compress in milliseconds.
    """

    entries_before: int = 0
    entries_after: int = 0
    removed: int = 0
    duration_ms: float = 0.0
