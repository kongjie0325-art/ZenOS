from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

__all__ = ["Knowledge", "VectorStore", "SemanticMemory"]


class VectorStore(Protocol):
    """Protocol defining the interface for a vector storage backend.

    Any vector store used with :class:`SemanticMemory` must implement
    these methods.
    """

    def upsert(self, id: str, vector: list[float], metadata: dict[str, Any]) -> None:
        """Insert or update a vector with associated metadata."""
        ...

    def search(
        self, query_vector: list[float], top_k: int = 5
    ) -> list[tuple[str, float]]:
        """Return the top-k nearest vectors as (id, score) pairs."""
        ...

    def delete(self, id: str) -> bool:
        """Remove a vector by id. Returns True if found."""
        ...


@dataclass
class Knowledge:
    """A unit of semantic knowledge.

    Attributes:
        id: Unique identifier for this knowledge item.
        content: The textual content / fact.
        timestamp: When the knowledge was created or last updated.
        metadata: Arbitrary metadata dictionary.
        embedding: Optional vector embedding for similarity search.
        importance: Scalar from 0.0 to 1.0 indicating significance.
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


class SemanticMemory:
    """Stores semantic knowledge items with optional vector-backed search.

    Knowledge items are held in an in-memory dictionary and, when a
    :class:`VectorStore` backend is provided, also persisted in the vector
    index for similarity search.
    """

    def __init__(self, vector_store: VectorStore | None = None) -> None:
        self._store: dict[str, Knowledge] = {}
        self._vector_store: VectorStore | None = vector_store

    def add_knowledge(self, knowledge: Knowledge) -> str:
        """Store a knowledge item.

        If a vector store is configured and the knowledge has an embedding,
        the vector is upserted into the backend as well.

        Args:
            knowledge: The knowledge item to store.

        Returns:
            The id of the stored knowledge.
        """
        self._store[knowledge.id] = knowledge
        if self._vector_store is not None and knowledge.embedding is not None:
            self._vector_store.upsert(
                knowledge.id,
                knowledge.embedding,
                {
                    "content": knowledge.content,
                    "importance": knowledge.importance,
                    **knowledge.metadata,
                },
            )
        return knowledge.id

    def search(
        self,
        query_vector: list[float] | None = None,
        query_text: str | None = None,
        top_k: int = 5,
        min_importance: float = 0.0,
    ) -> list[Knowledge]:
        """Search for knowledge items.

        If *query_vector* is provided and a vector store is configured,
        performs vector similarity search. Otherwise falls back to
        case-insensitive keyword matching on *query_text*.

        Args:
            query_vector: Optional embedding vector for similarity search.
            query_text: Optional text string for keyword search.
            top_k: Maximum number of results.
            min_importance: Minimum importance threshold.

        Returns:
            Matching knowledge items sorted by relevance / importance.
        """
        if query_vector is not None and self._vector_store is not None:
            return self._vector_search(query_vector, top_k, min_importance)
        if query_text is not None:
            return self._keyword_search(query_text, top_k, min_importance)
        # Return all above threshold, sorted by importance
        return sorted(
            (k for k in self._store.values() if k.importance >= min_importance),
            key=lambda k: -k.importance,
        )[:top_k]

    def update(self, knowledge_id: str, **kwargs: Any) -> Knowledge | None:
        """Update fields of an existing knowledge item.

        Args:
            knowledge_id: The id of the item to update.
            **kwargs: Fields to update (content, metadata, embedding, importance).

        Returns:
            The updated knowledge item, or None if not found.
        """
        if knowledge_id not in self._store:
            return None
        item = self._store[knowledge_id]
        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)
        item.timestamp = datetime.now()

        # Sync vector store if the embedding changed
        if self._vector_store is not None and "embedding" in kwargs:
            emb = item.embedding or kwargs["embedding"]
            if emb is not None:
                self._vector_store.upsert(
                    item.id,
                    emb,
                    {"content": item.content, "importance": item.importance, **item.metadata},
                )
        return item

    def delete(self, knowledge_id: str) -> bool:
        """Remove a knowledge item from storage.

        Args:
            knowledge_id: The id of the item to remove.

        Returns:
            True if the item was found and removed.
        """
        if knowledge_id not in self._store:
            return False
        del self._store[knowledge_id]
        if self._vector_store is not None:
            self._vector_store.delete(knowledge_id)
        return True

    def get_by_id(self, knowledge_id: str) -> Knowledge | None:
        """Retrieve a knowledge item by its id.

        Args:
            knowledge_id: The unique identifier.

        Returns:
            The knowledge item, or None if not found.
        """
        return self._store.get(knowledge_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _vector_search(
        self, query_vector: list[float], top_k: int, min_importance: float
    ) -> list[Knowledge]:
        """Perform vector similarity search."""
        assert self._vector_store is not None
        hits = self._vector_store.search(query_vector, top_k=top_k * 2)
        results: list[Knowledge] = []
        for kid, score in hits:
            item = self._store.get(kid)
            if item is not None and item.importance >= min_importance:
                results.append(item)
            if len(results) >= top_k:
                break
        return results

    def _keyword_search(
        self, query: str, top_k: int, min_importance: float
    ) -> list[Knowledge]:
        """Perform case-insensitive keyword search over content."""
        q = query.lower()
        results: list[Knowledge] = []
        for item in self._store.values():
            if item.importance < min_importance:
                continue
            if q in item.content.lower():
                results.append(item)
        results.sort(key=lambda k: -k.importance)
        return results[:top_k]

    def __len__(self) -> int:
        return len(self._store)
