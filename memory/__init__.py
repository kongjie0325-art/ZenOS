"""Memory module - Hierarchical memory system."""

from memory.working import WorkingMemory, WorkingMemoryEntry
from memory.episodic import EpisodicMemory, Episode
from memory.semantic import SemanticMemory, Knowledge
from memory.procedural import ProceduralMemory, Skill
from memory.compression import CompressionStrategy, CompressionConfig, CompressionReport
from memory.retrieval import RetrievalStrategy, RetrievalResult, MemoryRetriever

# Storage backends (optional - require redis/qdrant-client)
try:
    from memory.storage import MemoryEntry, MemoryStore, LocalMemoryStore
except ImportError:
    pass

__all__ = [
    'WorkingMemory', 'WorkingMemoryEntry',
    'EpisodicMemory', 'Episode',
    'SemanticMemory', 'Knowledge',
    'ProceduralMemory', 'Skill',
    'CompressionStrategy', 'CompressionConfig', 'CompressionReport',
    'RetrievalStrategy', 'RetrievalResult', 'MemoryRetriever',
    'MemoryEntry', 'MemoryStore', 'LocalMemoryStore',
]
