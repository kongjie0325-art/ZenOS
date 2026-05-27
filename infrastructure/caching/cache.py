"""Multi-tier cache with L1 LRU and L2 TTL layers."""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


class CacheStrategy(enum.Enum):
    """Cache population / eviction strategies."""

    LRU = "lru"
    TTL = "ttl"
    LFU = "lfu"


@dataclass
class CacheStats:
    """Snapshot of cache performance metrics.

    Attributes:
        hits: Total number of cache hits across both tiers.
        misses: Total number of cache misses.
        evictions: Total number of evictions across both tiers.
        l1_size: Current number of entries in the L1 cache.
        l1_capacity: Maximum capacity of the L1 cache.
        l2_size: Current number of entries in the L2 cache.
        l2_capacity: Maximum capacity of the L2 cache.
        hit_ratio: Fraction of lookups that were hits (0.0 – 1.0).
    """

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    l1_size: int = 0
    l1_capacity: int = 0
    l2_size: int = 0
    l2_capacity: int = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        total = self.total_requests
        return self.hits / total if total > 0 else 0.0


@dataclass
class _CacheEntry:
    """Internal representation of a cached value.

    Attributes:
        value: The cached payload.
        created_at: Monotonic timestamp when the entry was created.
        expires_at: Monotonic timestamp when the entry expires (None = never).
        access_count: Number of times this entry has been accessed.
        last_accessed: Monotonic timestamp of the most recent access.
    """

    value: Any
    created_at: float = field(default_factory=time.monotonic)
    expires_at: float | None = None
    access_count: int = 0
    last_accessed: float = field(default_factory=time.monotonic)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.monotonic() > self.expires_at


class MultiTierCache:
    """Two-tier cache combining an in-memory LRU (L1) and a TTL-backed layer (L2).

    On a get, the L1 layer is consulted first. On a miss, the L2 layer is checked.
    If the L2 has the value, it is promoted to L1. Expired entries are lazily
    evicted on access and during put operations when capacity is exceeded.

    Args:
        l1_capacity: Maximum number of items in the L1 LRU cache.
        l2_capacity: Maximum number of items in the L2 TTL cache.
        default_ttl: Default time-to-live in seconds for entries that do not
            specify an explicit TTL. ``None`` means no expiration.
        strategy: Eviction strategy for L2 when it is full.

    Example::

        cache = MultiTierCache(l1_capacity=128, l2_capacity=1024, default_ttl=300)
        cache.put("user:42", user_object, ttl=60)
        user = cache.get("user:42")
    """

    def __init__(
        self,
        l1_capacity: int = 256,
        l2_capacity: int = 4096,
        default_ttl: float | None = 300.0,
        strategy: CacheStrategy = CacheStrategy.LRU,
    ) -> None:
        self._l1_capacity = l1_capacity
        self._l2_capacity = l2_capacity
        self._default_ttl = default_ttl
        self._strategy = strategy

        # L1: OrderedDict gives us O(1) LRU via move_to_end + popitem(last=False)
        self._l1: OrderedDict[str, _CacheEntry] = OrderedDict()
        # L2: plain dict with TTL-based expiration
        self._l2: dict[str, _CacheEntry] = {}

        self._lock = threading.RLock()
        self._stats = CacheStats(l1_capacity=l1_capacity, l2_capacity=l2_capacity)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value from the cache.

        Checks L1 first, then L2. On an L2 hit the entry is promoted to L1.

        Args:
            key: Cache key to look up.
            default: Value to return on a miss.

        Returns:
            The cached value, or ``default`` if not found or expired.
        """
        with self._lock:
            # L1 check
            entry = self._l1.get(key)
            if entry is not None:
                if entry.is_expired:
                    del self._l1[key]
                    self._stats.misses += 1
                    return default
                entry.access_count += 1
                entry.last_accessed = time.monotonic()
                self._l1.move_to_end(key)
                self._stats.hits += 1
                return entry.value

            # L2 check
            entry = self._l2.get(key)
            if entry is not None:
                if entry.is_expired:
                    del self._l2[key]
                    self._stats.misses += 1
                    return default
                entry.access_count += 1
                entry.last_accessed = time.monotonic()
                self._stats.hits += 1
                # Promote to L1
                self._promote_to_l1(key, entry)
                return entry.value

            self._stats.misses += 1
            return default

    def put(
        self,
        key: str,
        value: Any,
        *,
        ttl: float | None = None,
    ) -> None:
        """Store a value in the cache.

        The value is always placed in L1. If L1 is full, the evicted entry
        is demoted to L2.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Optional TTL in seconds. Overrides ``default_ttl``.
        """
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = (
            time.monotonic() + effective_ttl if effective_ttl is not None else None
        )

        with self._lock:
            # If key already in L1, update in place
            if key in self._l1:
                entry = self._l1[key]
                entry.value = value
                entry.expires_at = expires_at
                entry.last_accessed = time.monotonic()
                self._l1.move_to_end(key)
                return

            # If key already in L2, remove it (will be reinserted into L1)
            self._l2.pop(key, None)

            # Evict from L1 if full, demoting the LRU entry to L2
            while len(self._l1) >= self._l1_capacity:
                self._evict_l1_oldest()

            entry = _CacheEntry(value=value, expires_at=expires_at)
            self._l1[key] = entry
            self._update_stats()

    def delete(self, key: str) -> bool:
        """Remove an entry from both cache tiers.

        Args:
            key: Cache key to remove.

        Returns:
            True if the key existed in either tier.
        """
        with self._lock:
            found = False
            if key in self._l1:
                del self._l1[key]
                found = True
            if key in self._l2:
                del self._l2[key]
                found = True
            self._update_stats()
            return found

    def clear(self) -> None:
        """Remove all entries from both cache tiers."""
        with self._lock:
            self._l1.clear()
            self._l2.clear()
            self._update_stats()
            logger.info("Cache cleared")

    def get_stats(self) -> CacheStats:
        """Return a snapshot of current cache statistics.

        Returns:
            A ``CacheStats`` dataclass with current metrics.
        """
        with self._lock:
            self._update_stats()
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                l1_size=len(self._l1),
                l1_capacity=self._l1_capacity,
                l2_size=len(self._l2),
                l2_capacity=self._l2_capacity,
            )

    def contains(self, key: str) -> bool:
        """Return True if the key exists in either tier and is not expired."""
        with self._lock:
            for store in (self._l1, self._l2):
                entry = store.get(key)
                if entry is not None and not entry.is_expired:
                    return True
            return False

    def keys(self) -> list[str]:
        """Return all non-expired keys across both tiers (L1 first)."""
        with self._lock:
            result: list[str] = []
            for k, e in self._l1.items():
                if not e.is_expired:
                    result.append(k)
            for k, e in self._l2.items():
                if not e.is_expired and k not in self._l1:
                    result.append(k)
            return result

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _promote_to_l1(self, key: str, entry: _CacheEntry) -> None:
        """Move an entry from L2 into L1, evicting the LRU item if needed."""
        while len(self._l1) >= self._l1_capacity:
            self._evict_l1_oldest()
        self._l1[key] = entry
        self._l2.pop(key, None)
        self._update_stats()

    def _evict_l1_oldest(self) -> None:
        """Evict the least-recently-used item from L1, demoting it to L2."""
        if not self._l1:
            return
        evicted_key, evicted_entry = self._l1.popitem(last=False)
        self._stats.evictions += 1
        # Demote to L2 if it hasn't expired and L2 has room
        if not evicted_entry.is_expired:
            self._make_room_in_l2()
            self._l2[evicted_key] = evicted_entry
        self._update_stats()

    def _make_room_in_l2(self) -> None:
        """Evict entries from L2 until there is at least one free slot."""
        # First remove expired entries
        expired = [k for k, e in self._l2.items() if e.is_expired]
        for k in expired:
            del self._l2[k]
            self._stats.evictions += 1

        # If still full, evict based on strategy
        while len(self._l2) >= self._l2_capacity:
            if not self._l2:
                break
            victim = self._select_l2_victim()
            del self._l2[victim]
            self._stats.evictions += 1

    def _select_l2_victim(self) -> str:
        """Select a victim key from L2 based on the configured strategy."""
        if self._strategy == CacheStrategy.LRU:
            return min(self._l2, key=lambda k: self._l2[k].last_accessed)
        if self._strategy == CacheStrategy.LFU:
            return min(self._l2, key=lambda k: self._l2[k].access_count)
        # TTL — evict the one closest to expiry
        def _remaining(k: str) -> float:
            e = self._l2[k]
            if e.expires_at is None:
                return float("inf")
            return e.expires_at - time.monotonic()

        return min(self._l2, key=_remaining)

    def _update_stats(self) -> None:
        """Keep the stats object in sync with current sizes."""
        self._stats.l1_size = len(self._l1)
        self._stats.l2_size = len(self._l2)
