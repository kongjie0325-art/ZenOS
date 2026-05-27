"""Predictive pre-fetching engine based on access pattern analysis."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class _AccessRecord:
    """Tracks access timestamps and co-occurrence for a single key."""

    timestamps: list[float] = field(default_factory=list)
    co_occurrences: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def count(self) -> int:
        return len(self.timestamps)

    @property
    def avg_interval(self) -> float | None:
        if len(self.timestamps) < 2:
            return None
        intervals = [
            self.timestamps[i + 1] - self.timestamps[i]
            for i in range(len(self.timestamps) - 1)
        ]
        return sum(intervals) / len(intervals)

    @property
    def interval_stddev(self) -> float | None:
        avg = self.avg_interval
        if avg is None or len(self.timestamps) < 3:
            return None
        intervals = [
            self.timestamps[i + 1] - self.timestamps[i]
            for i in range(len(self.timestamps) - 1)
        ]
        variance = sum((x - avg) ** 2 for x in intervals) / (len(intervals) - 1)
        return math.sqrt(variance)


@dataclass
class PatternStats:
    """Summary statistics for the predictive engine.

    Attributes:
        total_accesses: Total number of recorded accesses.
        unique_keys: Number of distinct keys that have been accessed.
        tracked_keys: Number of keys with enough data for predictions.
        prediction_accuracy: Fraction of prefetched keys that were
            subsequently accessed (0.0 – 1.0).
        prefetch_hits: Number of prefetched keys that were later accessed.
        prefetch_misses: Number of prefetched keys that were never accessed.
    """

    total_accesses: int = 0
    unique_keys: int = 0
    tracked_keys: int = 0
    prediction_accuracy: float = 0.0
    prefetch_hits: int = 0
    prefetch_misses: int = 0


class PredictivePrefetcher:
    """Analyzes cache access patterns and prefetches likely-to-be-needed items.

    The engine records every access and builds co-occurrence and interval
    statistics. When ``predict_next()`` is called, it returns keys that are
    statistically likely to be accessed soon. After a prefetch, the caller
    should call ``prefetch()`` so the engine can later evaluate accuracy.

    Args:
        min_samples: Minimum accesses before a key is considered for analysis.
        window: Sliding window of recent accesses (seconds) used for
            co-occurrence tracking.
        max_tracked_keys: Maximum number of keys to retain access history for.

    Example::

        prefetcher = PredictivePrefetcher()
        prefetcher.record_access("user:42")
        predicted = prefetcher.predict_next("user:42")
        for key in predicted:
            prefetcher.prefetch(key, loader_fn)
    """

    def __init__(
        self,
        min_samples: int = 3,
        window: float = 60.0,
        max_tracked_keys: int = 10000,
    ) -> None:
        self._min_samples = min_samples
        self._window = window
        self._max_tracked_keys = max_tracked_keys

        self._records: dict[str, _AccessRecord] = {}
        self._prefetched: set[str] = set()
        self._prefetch_hits = 0
        self._prefetch_misses = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def record_access(self, key: str) -> None:
        """Record that ``key`` was accessed at the current time.

        Also updates co-occurrence counts for other keys accessed within
        the configured time window.

        Args:
            key: The cache key that was accessed.
        """
        now = time.monotonic()
        with self._lock:
            rec = self._records.get(key)
            if rec is None:
                if len(self._records) >= self._max_tracked_keys:
                    self._evict_oldest_record()
                rec = _AccessRecord()
                self._records[key] = rec

            rec.timestamps.append(now)
            # Keep only the last 100 timestamps to bound memory
            if len(rec.timestamps) > 100:
                rec.timestamps = rec.timestamps[-100:]

            # Update co-occurrences with other keys in the window
            for other_key, other_rec in self._records.items():
                if other_key == key:
                    continue
                if other_rec.timestamps and (now - other_rec.timestamps[-1]) <= self._window:
                    rec.co_occurrences[other_key] += 1
                    other_rec.co_occurrences[key] += 1

            # If this key was prefetched, count a hit
            if key in self._prefetched:
                self._prefetched.discard(key)
                self._prefetch_hits += 1
                logger.debug("Prefetch hit for key %s", key)

    def predict_next(
        self,
        key: str,
        *,
        top_k: int = 5,
        min_score: float = 0.1,
    ) -> list[tuple[str, float]]:
        """Predict keys likely to be accessed next after ``key``.

        Scoring combines co-occurrence frequency and interval regularity.

        Args:
            key: The key that was just accessed.
            top_k: Maximum number of predictions to return.
            min_score: Minimum score threshold (0.0 – 1.0).

        Returns:
            A list of ``(predicted_key, score)`` pairs sorted by score
            descending. An empty list is returned if ``key`` has not been
            seen enough times.
        """
        with self._lock:
            rec = self._records.get(key)
            if rec is None or rec.count < self._min_samples:
                return []

            now = time.monotonic()
            scores: dict[str, float] = {}

            for co_key, co_count in rec.co_occurrences.items():
                co_rec = self._records.get(co_key)
                if co_rec is None:
                    continue

                # Co-occurrence score (normalized)
                co_score = co_count / rec.count

                # Timing score — how recently was co_key accessed?
                time_since = now - co_rec.timestamps[-1] if co_rec.timestamps else float("inf")
                avg_interval = co_rec.avg_interval
                if avg_interval and avg_interval > 0:
                    # Higher score if we're close to the expected next access
                    timing_score = max(0.0, 1.0 - abs(time_since - avg_interval) / avg_interval)
                else:
                    timing_score = 0.5  # Neutral when no interval data

                # Interval regularity bonus
                stddev = co_rec.interval_stddev
                regularity_bonus = 0.0
                if avg_interval and stddev is not None and avg_interval > 0:
                    cv = stddev / avg_interval  # coefficient of variation
                    regularity_bonus = max(0.0, 0.2 * (1.0 - cv))

                combined = 0.5 * co_score + 0.3 * timing_score + regularity_bonus
                if combined >= min_score:
                    scores[co_key] = round(combined, 4)

            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            return ranked[:top_k]

    def prefetch(
        self,
        key: str,
        loader: Callable[[str], Any],
        *,
        cache_put: Callable[[str, Any], None] | None = None,
    ) -> Any | None:
        """Prefetch a key by loading it and optionally placing it in a cache.

        Args:
            key: The key to prefetch.
            loader: Callable that takes a key and returns the value.
            cache_put: Optional ``(key, value)`` callable (e.g. ``cache.put``)
                to store the loaded value.

        Returns:
            The loaded value, or ``None`` if loading failed.
        """
        try:
            value = loader(key)
            self._prefetched.add(key)
            if cache_put is not None:
                cache_put(key, value)
            logger.debug("Prefetched key %s", key)
            return value
        except Exception:
            logger.exception("Prefetch failed for key %s", key)
            self._prefetch_misses += 1
            return None

    def get_pattern_stats(self) -> PatternStats:
        """Return statistics about access patterns and prediction accuracy.

        Returns:
            A ``PatternStats`` dataclass.
        """
        with self._lock:
            total_accesses = sum(r.count for r in self._records.values())
            tracked = sum(
                1 for r in self._records.values() if r.count >= self._min_samples
            )
            total_prefetch = self._prefetch_hits + self._prefetch_misses
            accuracy = (
                self._prefetch_hits / total_prefetch if total_prefetch > 0 else 0.0
            )
            return PatternStats(
                total_accesses=total_accesses,
                unique_keys=len(self._records),
                tracked_keys=tracked,
                prediction_accuracy=round(accuracy, 4),
                prefetch_hits=self._prefetch_hits,
                prefetch_misses=self._prefetch_misses,
            )

    def reset(self) -> None:
        """Clear all recorded access patterns and prefetch tracking."""
        with self._lock:
            self._records.clear()
            self._prefetched.clear()
            self._prefetch_hits = 0
            self._prefetch_misses = 0

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _evict_oldest_record(self) -> None:
        """Remove the least recently accessed record when capacity is full."""
        if not self._records:
            return
        oldest_key = min(
            self._records,
            key=lambda k: self._records[k].timestamps[-1]
            if self._records[k].timestamps
            else 0.0,
        )
        del self._records[oldest_key]
