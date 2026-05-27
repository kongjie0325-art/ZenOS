from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

__all__ = ["Episode", "EpisodicMemory"]


@dataclass
class Episode:
    """Represents a discrete episodic memory.

    Attributes:
        id: Unique identifier for the episode.
        content: The textual or structured content of the episode.
        timestamp: When the episode occurred.
        metadata: Arbitrary metadata associated with the episode.
        embedding: Optional vector embedding for semantic search.
        importance: Scalar from 0.0 (trivial) to 1.0 (critical).
    """

    content: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    importance: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.importance <= 1.0:
            raise ValueError(
                f"importance must be between 0 and 1, got {self.importance}"
            )


class EpisodicMemory:
    """Stores and retrieves episodic memories with temporal indexing.

    Episodes are stored in insertion order and can be queried by time range,
    importance threshold, or keyword search over content and metadata.
    """

    def __init__(self) -> None:
        self._episodes: dict[str, Episode] = {}
        # Temporal index: maps date string "YYYY-MM-DD" -> list of episode ids
        self._timeline_index: dict[str, list[str]] = {}

    def add_episode(self, episode: Episode) -> str:
        """Store an episode and index it temporally.

        Args:
            episode: The episode to store.

        Returns:
            The id of the stored episode.
        """
        self._episodes[episode.id] = episode
        date_key = episode.timestamp.strftime("%Y-%m-%d")
        self._timeline_index.setdefault(date_key, []).append(episode.id)
        return episode.id

    def get_episodes(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        min_importance: float = 0.0,
    ) -> list[Episode]:
        """Retrieve episodes filtered by time range and importance.

        Args:
            start: Inclusive start of the time range.
            end: Inclusive end of the time range.
            min_importance: Minimum importance threshold.

        Returns:
            Matching episodes sorted by timestamp ascending.
        """
        results: list[Episode] = []
        for ep in self._episodes.values():
            if ep.importance < min_importance:
                continue
            if start is not None and ep.timestamp < start:
                continue
            if end is not None and ep.timestamp > end:
                continue
            results.append(ep)
        results.sort(key=lambda e: e.timestamp)
        return results

    def search(self, query: str, limit: int = 10) -> list[Episode]:
        """Simple keyword search over episode content and metadata values.

        The query string is matched case-insensitively against the episode
        content and stringified metadata values.

        Args:
            query: Search string (case-insensitive).
            limit: Maximum number of results.

        Returns:
            Matching episodes ordered by importance descending.
        """
        q = query.lower()
        results: list[Episode] = []
        for ep in self._episodes.values():
            if q in ep.content.lower():
                results.append(ep)
                continue
            for v in ep.metadata.values():
                if isinstance(v, str) and q in v.lower():
                    results.append(ep)
                    break
        results.sort(key=lambda e: -e.importance)
        return results[:limit]

    def get_timeline(self, date: str) -> list[Episode]:
        """Return all episodes for a given date string (``YYYY-MM-DD``).

        Args:
            date: Date string in ``YYYY-MM-DD`` format.

        Returns:
            Episodes for that date, sorted by timestamp.
        """
        ids = self._timeline_index.get(date, [])
        episodes = [self._episodes[eid] for eid in ids if eid in self._episodes]
        episodes.sort(key=lambda e: e.timestamp)
        return episodes

    def forget(self, episode_id: str) -> bool:
        """Permanently remove an episode.

        Args:
            episode_id: The id of the episode to remove.

        Returns:
            True if the episode was found and removed.
        """
        ep = self._episodes.pop(episode_id, None)
        if ep is None:
            return False
        date_key = ep.timestamp.strftime("%Y-%m-%d")
        ids = self._timeline_index.get(date_key, [])
        if episode_id in ids:
            ids.remove(episode_id)
            if not ids:
                del self._timeline_index[date_key]
        return True

    def __len__(self) -> int:
        return len(self._episodes)
