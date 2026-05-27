"""Memory storage module."""

from memory.storage.memory_store import MemoryEntry, MemoryStore, LocalMemoryStore

__all__ = ["MemoryEntry", "MemoryStore", "LocalMemoryStore"]

# Optional backends
try:
    from memory.storage.redis_store import RedisStore, RedisStoreConfig
    __all__.extend(["RedisStore", "RedisStoreConfig"])
except (ImportError, ModuleNotFoundError):
    pass

try:
    from memory.storage.qdrant_store import QdrantStore, QdrantStoreConfig
    __all__.extend(["QdrantStore", "QdrantStoreConfig"])
except (ImportError, ModuleNotFoundError):
    pass
