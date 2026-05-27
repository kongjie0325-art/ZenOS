"""Memory storage module."""

from zenos.memory.storage.memory_store import MemoryEntry, MemoryStore, LocalMemoryStore

__all__ = ["MemoryEntry", "MemoryStore", "LocalMemoryStore"]

# Optional backends
try:
    from zenos.memory.storage.redis_store import RedisStore, RedisStoreConfig
    __all__.extend(["RedisStore", "RedisStoreConfig"])
except (ImportError, ModuleNotFoundError):
    pass

try:
    from zenos.memory.storage.qdrant_store import QdrantStore, QdrantStoreConfig
    __all__.extend(["QdrantStore", "QdrantStoreConfig"])
except (ImportError, ModuleNotFoundError):
    pass
