from __future__ import annotations

import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    """Generate a unique memory identifier."""
    return str(uuid.uuid4())


def _current_timestamp() -> float:
    """Return the current UTC timestamp as a float."""
    return time.time()


@dataclass
class MemoryEntry:
    """A single memory record stored in a MemoryStore.

    Attributes:
        id: Unique identifier for the memory entry.
        content: The primary textual content of the memory.
        metadata: Arbitrary key-value metadata attached to the memory.
        embedding: Optional vector representation of the content.
        created_at: Unix timestamp of creation.
        updated_at: Unix timestamp of last update.
        importance: Scalar importance score (0.0 – 1.0).
    """

    id: str = field(default_factory=_generate_id)
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    created_at: float = field(default_factory=_current_timestamp)
    updated_at: float = field(default_factory=_current_timestamp)
    importance: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        return cls(**data)


class MemoryStore(ABC):
    """Abstract base class for memory storage backends.

    All implementations must provide ``get``, ``put``, ``delete``,
    ``search``, and ``list_all`` methods.  Concrete backends may
    support additional capabilities such as vector similarity search
    or persistence to disk / remote services.
    """

    # -- lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Optional hook called once before first use."""

    async def close(self) -> None:
        """Release any underlying resources."""

    # -- CRUD --------------------------------------------------------------

    @abstractmethod
    async def get(self, memory_id: str) -> MemoryEntry | None:
        """Retrieve a single memory entry by its unique ID.

        Args:
            memory_id: The identifier of the memory to fetch.

        Returns:
            The matching ``MemoryEntry``, or ``None`` when not found.
        """
        ...

    @abstractmethod
    async def put(self, entry: MemoryEntry) -> str:
        """Persist a memory entry, assigning an ID if none is set.

        Args:
            entry: The memory entry to store.

        Returns:
            The ID of the stored entry.
        """
        ...

    @abstractmethod
    async def delete(self, memory_id: str) -> bool:
        """Remove a memory entry by its unique ID.

        Args:
            memory_id: The identifier of the memory to remove.

        Returns:
            ``True`` if the entry existed and was removed.
        """
        ...

    # -- queries -----------------------------------------------------------

    @abstractmethod
    async def search(self, query: str, *, limit: int = 10) -> list[MemoryEntry]:
        """Search for memory entries matching *query*.

        The default implementation performs a simple substring match
        over content and metadata values.  Subclasses may override
        with more sophisticated strategies (e.g. vector similarity).

        Args:
            query: Free-text search query.
            limit: Maximum number of results to return.

        Returns:
            A list of matching entries, best-first.
        """
        ...

    @abstractmethod
    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[MemoryEntry]:
        """Return all memory entries, paginated.

        Args:
            limit: Maximum page size.
            offset: Number of entries to skip.

        Returns:
            A list of memory entries.
        """
        ...

    # -- bulk helpers ------------------------------------------------------

    async def put_many(self, entries: list[MemoryEntry]) -> list[str]:
        """Persist multiple entries in sequence.

        Args:
            entries: Entries to store.

        Returns:
            List of stored IDs.
        """
        ids: list[str] = []
        for entry in entries:
            ids.append(await self.put(entry))
        return ids


class LocalMemoryStore(MemoryStore):
    """In-memory store backed by a JSON file on disk.

    This implementation keeps all entries in a ``dict`` in RAM and
    periodically (or on demand) flushes to a JSON file so that state
    survives restarts.

    Args:
        path: Filesystem path for the JSON persistence file.
        autosave: If ``True``, every mutating operation triggers a save.
    """

    def __init__(self, path: str | Path = "memory_store.json", *, autosave: bool = True) -> None:
        self._path = Path(path)
        self._autosave = autosave
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    # -- internal helpers --------------------------------------------------

    def _load(self) -> None:
        """Load entries from the JSON file, if it exists."""
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
                    logger.debug("Loaded %d entries from %s", len(self._data), self._path)
                    return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load %s: %s – starting empty", self._path, exc)
        self._data = {}

    def _save(self) -> None:
        """Persist the current in-memory state to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
            logger.debug("Saved %d entries to %s", len(self._data), self._path)
        except OSError as exc:
            logger.error("Failed to save memory store: %s", exc)

    def _maybe_save(self) -> None:
        if self._autosave:
            self._save()

    # -- MemoryStore implementation ----------------------------------------

    async def get(self, memory_id: str) -> MemoryEntry | None:
        raw = self._data.get(memory_id)
        if raw is None:
            return None
        return MemoryEntry.from_dict(raw)

    async def put(self, entry: MemoryEntry) -> str:
        if not entry.id:
            entry.id = _generate_id()
        entry.updated_at = _current_timestamp()
        self._data[entry.id] = entry.to_dict()
        self._maybe_save()
        return entry.id

    async def delete(self, memory_id: str) -> bool:
        if memory_id in self._data:
            del self._data[memory_id]
            self._maybe_save()
            return True
        return False

    async def search(self, query: str, *, limit: int = 10) -> list[MemoryEntry]:
        q = query.lower()
        scored: list[tuple[float, MemoryEntry]] = []
        for raw in self._data.values():
            entry = MemoryEntry.from_dict(raw)
            score = 0.0
            if q in entry.content.lower():
                score += 1.0
            for v in entry.metadata.values():
                if q in str(v).lower():
                    score += 0.5
            if score > 0:
                score += entry.importance * 0.1
                scored.append((score, entry))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[MemoryEntry]:
        entries = [MemoryEntry.from_dict(raw) for raw in self._data.values()]
        entries.sort(key=lambda e: e.updated_at, reverse=True)
        return entries[offset : offset + limit]

    # -- extra convenience -------------------------------------------------

    def save(self) -> None:
        """Explicitly flush to disk."""
        self._save()

    def clear(self) -> None:
        """Remove all entries from the store."""
        self._data.clear()
        self._maybe_save()

    @property
    def path(self) -> Path:
        return self._path

    def __len__(self) -> int:
        return len(self._data)
