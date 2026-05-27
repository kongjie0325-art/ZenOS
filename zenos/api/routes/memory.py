"""Memory API routes — search, add, delete, and compress endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional
from http import HTTPStatus

from zenos.api.routes.agent import Route, HttpMethod


@dataclass
class MemorySearchRequest:
    """Request body for memory search."""

    query: str
    limit: int = 10
    min_score: float = 0.0
    filters: dict[str, str] = field(default_factory=dict)


@dataclass
class MemoryEntry:
    """A single memory search result."""

    id: str
    content: str
    score: float
    created_at: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class MemorySearchResponse:
    """Response from a memory search."""

    results: list[MemoryEntry] = field(default_factory=list)
    total: int = 0
    query_time_ms: float = 0.0


@dataclass
class MemoryAddRequest:
    """Request body for adding a memory entry."""

    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class MemoryAddResponse:
    """Response from adding a memory entry."""

    id: str
    status: str = "created"
    created_at: float = 0.0


@dataclass
class MemoryDeleteResponse:
    """Response from deleting a memory entry."""

    id: str
    status: str = "deleted"
    deleted: bool = True


@dataclass
class MemoryCompressRequest:
    """Request body for memory compression."""

    strategy: str = "summarize"  # "summarize", "deduplicate", "prune"
    older_than_days: Optional[int] = None
    max_entries: Optional[int] = None


@dataclass
class MemoryCompressResponse:
    """Response from memory compression."""

    entries_before: int = 0
    entries_after: int = 0
    removed: int = 0
    duration_ms: float = 0.0


class MemoryRouter:
    """Memory route handler — manages memory CRUD and compression.

    Provides endpoints to search, add, delete, and compress
    agent memory entries.
    """

    def __init__(self) -> None:
        self._routes = self._build_routes()
        self._entries: dict[str, MemoryEntry] = {}

    @property
    def routes(self) -> list[Route]:
        """Return the list of registered routes."""
        return self._routes

    def _build_routes(self) -> list[Route]:
        """Register all memory routes."""
        return [
            Route(
                path="/api/v1/memory/search",
                method=HttpMethod.POST,
                handler=self.search,
                name="memory_search",
            ),
            Route(
                path="/api/v1/memory/add",
                method=HttpMethod.POST,
                handler=self.add,
                name="memory_add",
            ),
            Route(
                path="/api/v1/memory/delete/{entry_id}",
                method=HttpMethod.DELETE,
                handler=self.delete,
                name="memory_delete",
            ),
            Route(
                path="/api/v1/memory/compress",
                method=HttpMethod.POST,
                handler=self.compress,
                name="memory_compress",
            ),
        ]

    def search(
        self,
        request: MemorySearchRequest,
        **kwargs: Any,
    ) -> MemorySearchResponse:
        """Search memory entries by semantic similarity.

        Args:
            request: Search parameters including query and filters.

        Returns:
            MemorySearchResponse with matching entries sorted by score.
        """
        import uuid

        start = time.time()
        # Placeholder: in production this would query a vector store.
        results = [
            MemoryEntry(
                id=str(uuid.uuid4()),
                content=f"Placeholder result for: {request.query}",
                score=0.95,
                created_at=time.time(),
            )
        ]
        elapsed = (time.time() - start) * 1000
        return MemorySearchResponse(
            results=results[: request.limit],
            total=len(results),
            query_time_ms=round(elapsed, 2),
        )

    def add(
        self,
        request: MemoryAddRequest,
        **kwargs: Any,
    ) -> MemoryAddResponse:
        """Add a new memory entry.

        Args:
            request: The memory content and metadata to store.

        Returns:
            MemoryAddResponse with the new entry ID.
        """
        import uuid

        entry_id = str(uuid.uuid4())
        now = time.time()
        self._entries[entry_id] = MemoryEntry(
            id=entry_id,
            content=request.content,
            score=1.0,
            created_at=now,
            metadata={**request.metadata, "tags": ",".join(request.tags)},
        )
        return MemoryAddResponse(id=entry_id, status="created", created_at=now)

    def delete(
        self,
        entry_id: str,
        **kwargs: Any,
    ) -> MemoryDeleteResponse:
        """Delete a memory entry by ID.

        Args:
            entry_id: The unique memory entry identifier.

        Returns:
            MemoryDeleteResponse confirming deletion.
        """
        if entry_id not in self._entries:
            return MemoryDeleteResponse(
                id=entry_id, status="not_found", deleted=False
            )
        del self._entries[entry_id]
        return MemoryDeleteResponse(id=entry_id, status="deleted", deleted=True)

    def compress(
        self,
        request: MemoryCompressRequest,
        **kwargs: Any,
    ) -> MemoryCompressResponse:
        """Compress memory entries using the specified strategy.

        Args:
            request: Compression parameters (strategy, age threshold, etc.).

        Returns:
            MemoryCompressResponse with before/after counts.
        """
        start = time.time()
        before = len(self._entries)
        # Placeholder: actual compression logic depends on strategy.
        after = before
        elapsed = (time.time() - start) * 1000
        return MemoryCompressResponse(
            entries_before=before,
            entries_after=after,
            removed=before - after,
            duration_ms=round(elapsed, 2),
        )
