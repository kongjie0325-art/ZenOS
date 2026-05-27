from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = ["CompressionStrategy", "CompressionConfig", "MemoryCompressor"]


class CompressionStrategy(Enum):
    """Available strategies for memory compression.

    - ``summarize``: Keep only the most important entries and summarize.
    - ``prune``: Remove low-importance / low-priority entries entirely.
    - ``consolidate``: Merge similar entries into a single compressed entry.
    """

    SUMMARIZE = "summarize"
    PRUNE = "prune"
    CONSOLIDATE = "consolidate"


@dataclass
class CompressionConfig:
    """Configuration for memory compression behaviour.

    Attributes:
        strategy: Which compression strategy to apply.
        threshold: Fraction of capacity at which compression triggers
            (e.g. 0.8 = compress when 80 % full).
        min_importance_to_keep: Minimum importance/priority for an entry
            to survive pruning.
        max_entries_after: Hard cap on the number of entries after compression.
    """

    strategy: CompressionStrategy = CompressionStrategy.PRUNE
    threshold: float = 0.8
    min_importance_to_keep: float = 0.3
    max_entries_after: int = 128


@dataclass
class CompressionReport:
    """Summary of a compression run.

    Attributes:
        strategy_used: The strategy that was applied.
        entries_before: Number of entries before compression.
        entries_after: Number of entries after compression.
        removed_count: How many entries were removed or merged.
        details: Optional human-readable summary of what changed.
    """

    strategy_used: CompressionStrategy
    entries_before: int
    entries_after: int
    removed_count: int
    details: str = ""


class MemoryCompressor:
    """Compresses working and episodic memory to manage capacity.

    Uses configurable strategies to reduce memory footprint while
    preserving the most important information.
    """

    def __init__(self, config: CompressionConfig | None = None) -> None:
        self.config: CompressionConfig = config or CompressionConfig()

    def compress_working(
        self, memory: WorkingMemory
    ) -> CompressionReport:
        """Compress a :class:`WorkingMemory` instance.

        Args:
            memory: The working memory to compress.

        Returns:
            A report describing what was done.
        """
        before = len(memory)
        strategy = self.config.strategy

        if strategy == CompressionStrategy.PRUNE:
            self._prune_working(memory)
        elif strategy == CompressionStrategy.SUMMARIZE:
            self._summarize_working(memory)
        elif strategy == CompressionStrategy.CONSOLIDATE:
            self._consolidate_working(memory)

        after = len(memory)
        return CompressionReport(
            strategy_used=strategy,
            entries_before=before,
            entries_after=after,
            removed_count=before - after,
            details=f"Working memory compressed from {before} to {after} entries.",
        )

    def compress_episodic(
        self, memory: EpisodicMemory, start_date: str | None = None, end_date: str | None = None
    ) -> CompressionReport:
        """Compress an :class:`EpisodicMemory` by removing low-importance
        episodes outside an optional date range.

        Args:
            memory: The episodic memory to compress.
            start_date: If provided, only consider episodes on or after this
                date (``YYYY-MM-DD``).
            end_date: If provided, only consider episodes on or before this
                date.

        Returns:
            A report describing what was done.
        """
        from datetime import datetime

        before = len(memory)
        min_imp = self.config.min_importance_to_keep

        # If date range is specified, only compress within that range
        start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None

        if start or end:
            candidates = memory.get_episodes(start=start, end=end)
        else:
            # Get all episodes with low importance
            candidates = [
                ep for ep in memory.get_episodes()
                if ep.importance < min_imp
            ]

        removed = 0
        for ep in candidates:
            if memory.forget(ep.id):
                removed += 1

        after = len(memory)
        return CompressionReport(
            strategy_used=CompressionStrategy.PRUNE,
            entries_before=before,
            entries_after=after,
            removed_count=removed,
            details=(
                f"Episodic memory compressed from {before} to {after} "
                f"entries (removed {removed} low-importance episodes)."
            ),
        )

    def summarize(self, entries: list[str], max_length: int = 512) -> str:
        """Produce a concise summary from a list of text entries.

        This is a rule-based placeholder that joins and truncates. In a
        production system this would call an LLM or summarization model.

        Args:
            entries: Text entries to summarize.
            max_length: Maximum character length of the summary.

        Returns:
            A summarized string.
        """
        combined = " ".join(entries)
        if len(combined) <= max_length:
            return combined
        # Truncate at the last complete sentence within the limit
        truncated = combined[:max_length]
        last_period = truncated.rfind(".")
        if last_period > 0:
            return truncated[: last_period + 1]
        return truncated + "…"

    def should_compress(self, current_size: int, capacity: int) -> bool:
        """Determine whether compression should be triggered.

        Args:
            current_size: Current number of entries.
            capacity: Maximum capacity.

        Returns:
            True if the usage ratio exceeds the configured threshold.
        """
        if capacity <= 0:
            return True
        return (current_size / capacity) >= self.config.threshold

    # ------------------------------------------------------------------
    # Internal strategy implementations
    # ------------------------------------------------------------------

    def _prune_working(self, memory: WorkingMemory) -> None:
        """Remove low-priority entries from working memory."""
        min_priority = int(self.config.min_importance_to_keep * 10)
        entries = memory.get_by_priority(min_priority=min_priority)
        keep_ids = {e.id for e in entries}
        # Remove everything not in the keep set
        all_entries = memory.get_by_priority(min_priority=0)
        for entry in all_entries:
            if entry.id not in keep_ids:
                memory.remove(entry.id)

    def _summarize_working(self, memory: WorkingMemory) -> None:
        """Summarize working memory by keeping top entries and compressing."""
        self._prune_working(memory)
        # After pruning, if still over max_entries_after, do LRU eviction
        while len(memory) > self.config.max_entries_after:
            memory.evict_lru()

    def _consolidate_working(self, memory: WorkingMemory) -> None:
        """Consolidate by pruning then evicting LRU to target size."""
        self._prune_working(memory)
        while len(memory) > self.config.max_entries_after:
            memory.evict_lru()
