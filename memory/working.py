from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

__all__ = ["WorkingMemoryEntry", "WorkingMemory"]


@dataclass
class WorkingMemoryEntry:
    """A single entry in working memory.

    Attributes:
        id: Unique identifier for the entry.
        content: The payload stored in this entry.
        priority: Priority level (higher = more important). Defaults to 0.
        ttl: Time-to-live in seconds. None means no expiration.
        metadata: Arbitrary metadata dictionary.
        created_at: Unix timestamp when the entry was created.
        last_accessed_at: Unix timestamp of the last access.
        access_count: Number of times this entry has been accessed.
    """

    id: str
    content: Any
    priority: int = 0
    ttl: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    access_count: int = 0

    @property
    def is_expired(self) -> bool:
        """Check whether this entry has exceeded its TTL."""
        if self.ttl is None:
            return False
        return (time.time() - self.created_at) > self.ttl

    def touch(self) -> None:
        """Update the last-accessed timestamp and increment access count."""
        self.last_accessed_at = time.time()
        self.access_count += 1


class WorkingMemory:
    """In-memory working memory store with LRU eviction, TTL expiration, and
    priority-based retrieval.

    This class maintains a bounded collection of :class:`WorkingMemoryEntry`
    items. When the capacity is exceeded the least-recently-used entry is
    evicted automatically. Expired entries (based on TTL) are lazily removed
    on access and can be proactively cleaned with :meth:`evict_lru`.

    Attributes:
        capacity: Maximum number of entries allowed.
    """

    def __init__(self, capacity: int = 256) -> None:
        """Initialize the working memory.

        Args:
            capacity: Maximum number of entries before LRU eviction fires.
        """
        self.capacity: int = capacity
        self._store: OrderedDict[str, WorkingMemoryEntry] = OrderedDict()
        self._lock = Lock()

    def add(self, entry: WorkingMemoryEntry) -> None:
        """Add an entry to working memory.

        If an entry with the same id already exists it is replaced. If the
        store is at capacity the least-recently-used entry is evicted first.

        Args:
            entry: The working-memory entry to store.
        """
        with self._lock:
            if entry.id in self._store:
                self._store.move_to_end(entry.id)
                self._store[entry.id] = entry
            else:
                if len(self._store) >= self.capacity:
                    self._evict_one_lru()
                self._store[entry.id] = entry

    def get(self, entry_id: str) -> WorkingMemoryEntry | None:
        """Retrieve an entry by id.

        Marks the entry as most-recently-used and updates its access
        statistics. Returns None if the entry is missing or expired.

        Args:
            entry_id: The unique id of the entry.

        Returns:
            The entry, or None if not found / expired.
        """
        with self._lock:
            if entry_id not in self._store:
                return None
            entry = self._store[entry_id]
            if entry.is_expired:
                del self._store[entry_id]
                return None
            entry.touch()
            self._store.move_to_end(entry_id)
            return entry

    def remove(self, entry_id: str) -> bool:
        """Remove an entry by id.

        Args:
            entry_id: The unique id of the entry to remove.

        Returns:
            True if the entry was found and removed, False otherwise.
        """
        with self._lock:
            if entry_id in self._store:
                del self._store[entry_id]
                return True
            return False

    def clear(self) -> int:
        """Remove all entries.

        Returns:
            The number of entries that were cleared.
        """
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about the working memory.

        Returns:
            A dict with capacity, size, expired_count,
            average_access_count, and priority_distribution.
        """
        with self._lock:
            expired = sum(1 for e in self._store.values() if e.is_expired)
            total_access = sum(e.access_count for e in self._store.values())
            size = len(self._store)
            return {
                "capacity": self.capacity,
                "size": size,
                "expired_count": expired,
                "average_access_count": (total_access / size) if size else 0.0,
                "priority_distribution": self._priority_distribution(),
            }

    def evict_lru(self) -> int:
        """Evict expired entries and, if still over capacity, LRU entries.

        Returns:
            The number of entries evicted.
        """
        with self._lock:
            evicted = self._evict_expired()
            while len(self._store) > self.capacity:
                self._evict_one_lru()
                evicted += 1
            return evicted

    def get_by_priority(self, min_priority: int = 0) -> list[WorkingMemoryEntry]:
        """Return entries with priority >= *min_priority*, sorted by
        priority descending then most-recently-used first.

        Args:
            min_priority: Minimum priority threshold (inclusive).

        Returns:
            A list of matching entries.
        """
        with self._lock:
            entries = [
                e for e in self._store.values()
                if e.priority >= min_priority and not e.is_expired
            ]
            entries.sort(key=lambda e: (-e.priority, -e.last_accessed_at))
            return entries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_one_lru(self) -> None:
        """Evict the single least-recently-used entry."""
        if self._store:
            self._store.popitem(last=False)

    def _evict_expired(self) -> int:
        """Remove all expired entries. Returns count evicted."""
        expired_ids = [k for k, v in self._store.items() if v.is_expired]
        for eid in expired_ids:
            del self._store[eid]
        return len(expired_ids)

    def _priority_distribution(self) -> dict[int, int]:
        """Return a mapping of priority -> count for current entries."""
        dist: dict[int, int] = {}
        for entry in self._store.values():
            dist[entry.priority] = dist.get(entry.priority, 0) + 1
        return dist

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, entry_id: str) -> bool:
        return entry_id in self._store
