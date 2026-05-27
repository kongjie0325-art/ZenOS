from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .memory_store import MemoryEntry, MemoryStore

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "redis package is required for RedisStore. Install via: pip install redis"
    ) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_entry(entry: MemoryEntry) -> str:
    """Convert a ``MemoryEntry`` to a JSON string."""
    data = entry.to_dict()
    return json.dumps(data, ensure_ascii=False)


def _deserialize_entry(raw: str) -> MemoryEntry:
    """Parse a JSON string back into a ``MemoryEntry``."""
    return MemoryEntry.from_dict(json.loads(raw))


# ---------------------------------------------------------------------------
# Redis-backed store
# ---------------------------------------------------------------------------

@dataclass
class RedisStoreConfig:
    """Configuration for ``RedisStore``.

    Attributes:
        host: Redis server hostname.
        port: Redis server port.
        db: Redis database number.
        password: Optional authentication password.
        key_prefix: Prefix applied to every Redis key.
        index_hash: Hash key that holds the full entry payloads.
        index_set: Sorted-set key for chronological ordering.
        socket_timeout: Connection timeout in seconds.
    """

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    key_prefix: str = "zenos:memory"
    index_hash: str = "zenos:memory:data"
    index_set: str = "zenos:memory:by_time"
    socket_timeout: float = 5.0


class RedisStore(MemoryStore):
    """Async Redis-backed implementation of ``MemoryStore``.

    Entries are stored as JSON strings in a Redis hash keyed by
    memory ID.  A secondary sorted set (score = ``updated_at``)
    provides efficient chronological listing.

    Args:
        config: Connection and key-naming configuration.
        client: An existing ``redis.asyncio.Redis`` client.  When
            ``None``, a new client is created from *config*.
    """

    def __init__(
        self,
        config: RedisStoreConfig | None = None,
        *,
        client: redis.Redis | None = None,
    ) -> None:
        self._config = config or RedisStoreConfig()
        self._client = client
        self._owns_client = client is None

    # -- lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Create the Redis connection if one was not supplied."""
        if self._client is None:
            self._client = redis.Redis(
                host=self._config.host,
                port=self._config.port,
                db=self._config.db,
                password=self._config.password,
                socket_timeout=self._config.socket_timeout,
                decode_responses=True,
            )
            logger.info(
                "RedisStore connected to %s:%d db=%d",
                self._config.host,
                self._config.port,
                self._config.db,
            )

    async def close(self) -> None:
        """Close the connection if we own it."""
        if self._owns_client and self._client is not None:
            await self._client.close()
            logger.info("RedisStore connection closed")

    # -- internal helpers --------------------------------------------------

    def _ensure_client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("RedisStore is not initialized – call initialize() first")
        return self._client

    # -- MemoryStore implementation ----------------------------------------

    async def get(self, memory_id: str) -> MemoryEntry | None:
        client = self._ensure_client()
        raw = await client.hget(self._config.index_hash, memory_id)
        if raw is None:
            return None
        return _deserialize_entry(raw)

    async def put(self, entry: MemoryEntry) -> str:
        client = self._ensure_client()
        entry.updated_at = entry.updated_at  # already set
        serialized = _serialize_entry(entry)
        pipe = client.pipeline(True)
        pipe.hset(self._config.index_hash, entry.id, serialized)
        pipe.zadd(self._config.index_set, {entry.id: entry.updated_at})
        await pipe.execute()
        return entry.id

    async def delete(self, memory_id: str) -> bool:
        client = self._ensure_client()
        pipe = client.pipeline(True)
        pipe.hdel(self._config.index_hash, memory_id)
        pipe.zrem(self._config.index_set, memory_id)
        results = await pipe.execute()
        return bool(results[0] > 0)

    async def search(self, query: str, *, limit: int = 10) -> list[MemoryEntry]:
        client = self._ensure_client()
        q = query.lower()

        # Scan the hash for substring matches.
        # For large datasets consider Redisearch; this is a pragmatic fallback.
        cursor = 0
        scored: list[tuple[float, MemoryEntry]] = []
        while True:
            cursor, batch = await client.hscan(self._config.index_hash, cursor, count=200)
            for _key, raw in batch.items():
                entry = _deserialize_entry(raw)
                score = 0.0
                if q in entry.content.lower():
                    score += 1.0
                for v in entry.metadata.values():
                    if q in str(v).lower():
                        score += 0.5
                if score > 0:
                    score += entry.importance * 0.1
                    scored.append((score, entry))
            if cursor == 0:
                break

        scored.sort(key=lambda t: t[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[MemoryEntry]:
        client = self._ensure_client()
        ids: list[str] = await client.zrevrange(
            self._config.index_set, offset, offset + limit - 1
        )
        if not ids:
            return []
        raws = await client.hmget(self._config.index_hash, ids)
        entries: list[MemoryEntry] = []
        for raw in raws:
            if raw is not None:
                entries.append(_deserialize_entry(raw))
        return entries

    # -- bulk helpers ------------------------------------------------------

    async def put_many(self, entries: list[MemoryEntry]) -> list[str]:
        client = self._ensure_client()
        pipe = client.pipeline(True)
        ids: list[str] = []
        for entry in entries:
            entry.updated_at = entry.updated_at
            pipe.hset(self._config.index_hash, entry.id, _serialize_entry(entry))
            pipe.zadd(self._config.index_set, {entry.id: entry.updated_at})
            ids.append(entry.id)
        await pipe.execute()
        return ids

    # -- extra -------------------------------------------------------------

    async def count(self) -> int:
        """Return the number of entries in the store."""
        client = self._ensure_client()
        return int(await client.hlen(self._config.index_hash))

    async def clear(self) -> bool:
        """Delete **all** entries.  Returns ``True`` on success."""
        client = self._ensure_client()
        pipe = client.pipeline(True)
        pipe.delete(self._config.index_hash)
        pipe.delete(self._config.index_set)
        await pipe.execute()
        return True
