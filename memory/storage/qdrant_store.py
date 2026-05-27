from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .memory_store import MemoryEntry, MemoryStore

logger = logging.getLogger(__name__)

try:
    from qdrant_client import AsyncQdrantClient, models
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchText,
        MatchValue,
        PointStruct,
        ScoredPoint,
        VectorParams,
    )
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "qdrant-client is required for QdrantStore. Install via: pip install qdrant-client"
    ) from exc


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class QdrantStoreConfig:
    """Configuration for ``QdrantStore``.

    Attributes:
        host: Qdrant server hostname.
        port: Qdrant server REST API port.
        grpc_port: Qdrant gRPC port.
        collection: Name of the Qdrant collection to use.
        vector_size: Dimensionality of stored embeddings.
        distance: Distance metric for similarity search.
        api_key: Optional API key for authenticated Qdrant instances.
        prefer_grpc: Use gRPC for point operations when available.
        on_disk: Store vectors on disk instead of in RAM.
    """

    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    collection: str = "zenos_memory"
    vector_size: int = 1536
    distance: Distance = Distance.COSINE
    api_key: str | None = None
    prefer_grpc: bool = True
    on_disk: bool = False


# ---------------------------------------------------------------------------
# Qdrant-backed vector store
# ---------------------------------------------------------------------------

class QdrantStore(MemoryStore):
    """Async Qdrant-backed implementation of ``MemoryStore``.

    Stores each ``MemoryEntry`` as a Qdrant point whose vector is
    ``entry.embedding`` and whose payload holds the remaining fields
    (``id``, ``content``, ``metadata``, timestamps, importance).

    If no embedding is provided at put-time, a zero-vector is used as a
    placeholder so the point is still indexed; callers should update the
    vector later via :meth:`update_embedding`.

    Args:
        config: Connection and collection configuration.
        client: An existing ``AsyncQdrantClient``.  When ``None``, a
            new client is created from *config*.
    """

    def __init__(
        self,
        config: QdrantStoreConfig | None = None,
        *,
        client: AsyncQdrantClient | None = None,
    ) -> None:
        self._config = config or QdrantStoreConfig()
        self._client = client
        self._owns_client = client is None

    # -- lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Create the Qdrant client and ensure the collection exists."""
        if self._client is None:
            self._client = AsyncQdrantClient(
                host=self._config.host,
                port=self._config.port,
                grpc_port=self._config.grpc_port,
                api_key=self._config.api_key,
                prefer_grpc=self._config.prefer_grpc,
            )
            logger.info(
                "QdrantStore connected to %s:%d (collection=%s)",
                self._config.host,
                self._config.port,
                self._config.collection,
            )
        await self._ensure_collection()

    async def _ensure_collection(self) -> None:
        client = self._ensure_client()
        existing = await client.get_collections()
        names = {c.name for c in existing.collections}
        if self._config.collection in names:
            return

        await client.create_collection(
            collection_name=self._config.collection,
            vectors_config=VectorParams(
                size=self._config.vector_size,
                distance=self._config.distance,
                on_disk=self._config.on_disk,
            ),
        )
        # Payload indexes for fast filtering
        await client.create_payload_index(
            collection_name=self._config.collection,
            field_name="importance",
            field_type="float",
        )
        await client.create_payload_index(
            collection_name=self._config.collection,
            field_name="created_at",
            field_type="float",
        )
        logger.info("Created Qdrant collection '%s'", self._config.collection)

    async def close(self) -> None:
        """Close the client if we own it."""
        if self._owns_client and self._client is not None:
            await self._client.close()
            logger.info("QdrantStore connection closed")

    # -- internal helpers --------------------------------------------------

    def _ensure_client(self) -> AsyncQdrantClient:
        if self._client is None:
            raise RuntimeError("QdrantStore is not initialized – call initialize() first")
        return self._client

    @staticmethod
    def _entry_to_point(entry: MemoryEntry) -> PointStruct:
        vector = entry.embedding or [0.0] * 1536  # placeholder
        payload = {
            "id": entry.id,
            "content": entry.content,
            "metadata": entry.metadata,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "importance": entry.importance,
        }
        return PointStruct(id=entry.id, vector=vector, payload=payload)

    @staticmethod
    def _scored_point_to_entry(point: ScoredPoint) -> MemoryEntry:
        p = point.payload or {}
        return MemoryEntry(
            id=p.get("id", str(point.id)),
            content=p.get("content", ""),
            metadata=p.get("metadata", {}),
            embedding=point.vector if isinstance(point.vector, list) else None,
            created_at=p.get("created_at", 0.0),
            updated_at=p.get("updated_at", 0.0),
            importance=p.get("importance", 0.5),
        )

    # -- MemoryStore implementation ----------------------------------------

    async def get(self, memory_id: str) -> MemoryEntry | None:
        client = self._ensure_client()
        points = await client.retrieve(
            collection_name=self._config.collection,
            ids=[memory_id],
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            return None
        return self._scored_point_to_entry(
            ScoredPoint(
                id=points[0].id,
                version=0,
                score=0.0,
                payload=points[0].payload,
                vector=points[0].vector,
            )
        )

    async def put(self, entry: MemoryEntry) -> str:
        client = self._ensure_client()
        if not entry.id:
            entry.id = str(uuid.uuid4())
        entry.updated_at = time.time()
        point = self._entry_to_point(entry)
        await client.upsert(
            collection_name=self._config.collection,
            points=[point],
        )
        return entry.id

    async def delete(self, memory_id: str) -> bool:
        client = self._ensure_client()
        result = await client.delete(
            collection_name=self._config.collection,
            points_selector=models.PointIdsList(points=[memory_id]),
        )
        # Qdrant returns an operation status; treat any non-error as success
        return True

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        query_vector: list[float] | None = None,
        min_score: float = 0.0,
    ) -> list[MemoryEntry]:
        """Search by vector similarity, keyword, or both.

        If *query_vector* is supplied, a vector similarity search is
        performed.  Otherwise a full-text payload search on the
        ``content`` field is used.

        Args:
            query: Text query (used for keyword search when no vector).
            limit: Maximum results.
            query_vector: Optional embedding for the query.
            min_score: Minimum similarity score threshold.
        """
        client = self._ensure_client()
        if query_vector is not None:
            scored_points = await client.search(
                collection_name=self._config.collection,
                query_vector=query_vector,
                query_filter=None,
                limit=limit,
                score_threshold=min_score,
                with_payload=True,
                with_vectors=False,
            )
        else:
            scored_points = await client.scroll(
                collection_name=self._config.collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="content",
                            match=MatchText(text=query),
                        )
                    ]
                ),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            # scroll returns (points, next_page_offset); adapt to scored list
            scored_points = [
                ScoredPoint(id=p.id, version=0, score=1.0, payload=p.payload, vector=None)
                for p in scored_points[0]
            ]

        return [self._scored_point_to_entry(sp) for sp in scored_points]

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[MemoryEntry]:
        client = self._ensure_client()
        points, _ = await client.scroll(
            collection_name=self._config.collection,
            limit=limit,
            offset=None if offset == 0 else str(offset),
            with_payload=True,
            with_vectors=False,
            order_by=models.OrderBy(key="updated_at", direction="desc"),
        )
        return [
            self._scored_point_to_entry(
                ScoredPoint(id=p.id, version=0, score=0.0, payload=p.payload, vector=None)
            )
            for p in points
        ]

    # -- vector-specific helpers -------------------------------------------

    async def update_embedding(self, memory_id: str, embedding: list[float]) -> None:
        """Replace the vector for an existing point without re-uploading payload."""
        client = self._ensure_client()
        await client.update_vectors(
            collection_name=self._config.collection,
            points=[
                models.PointVectors(
                    id=memory_id,
                    vector=embedding,
                )
            ],
        )

    async def search_by_metadata(
        self,
        key: str,
        value: Any,
        *,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Return entries whose metadata *key* matches *value*."""
        client = self._ensure_client()
        points, _ = await client.scroll(
            collection_name=self._config.collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key=f"metadata.{key}",
                        match=MatchValue(value=value),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [
            self._scored_point_to_entry(
                ScoredPoint(id=p.id, version=0, score=0.0, payload=p.payload, vector=None)
            )
            for p in points
        ]

    async def count(self) -> int:
        client = self._ensure_client()
        result = await client.count(collection_name=self._config.collection)
        return result.count

    async def clear(self) -> None:
        """Delete the entire collection and recreate it."""
        client = self._ensure_client()
        await client.delete_collection(self._config.collection)
        await self._ensure_collection()
        logger.info("Qdrant collection '%s' reset", self._config.collection)
