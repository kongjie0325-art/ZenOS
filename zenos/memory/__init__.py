"""Memory module - Hierarchical memory system (3-tier in-memory + 4-tier production).

Three-Tier (in-memory, single machine):
  WorkingMemory  → EpisodicMemory → SemanticMemory
  (LRU cache)      (time-indexed)   (vector search)

Four-Tier (production, distributed):
  Redis (Tier 1) → PostgreSQL (Tier 2) → Qdrant (Tier 3) → S3 (Tier 4)
  (hot cache)       (structured)         (vectors)        (cold storage)
"""

# Three-Tier (existing, in-memory)
from zenos.memory.working import WorkingMemory, WorkingMemoryEntry
from zenos.memory.episodic import EpisodicMemory, Episode
from zenos.memory.semantic import SemanticMemory, Knowledge
from zenos.memory.procedural import ProceduralMemory, Skill
from zenos.memory.compression import CompressionStrategy, CompressionConfig, CompressionReport
from zenos.memory.retrieval import RetrievalStrategy, RetrievalResult, MemoryRetriever
from zenos.memory.memory_graph import MemoryGraph, GraphNode, GraphEdge

# Four-Tier (production, distributed)
from zenos.memory.four_tier import (
    RedisWorkingMemory,
    PostgreEpisodicMemory,
    QdrantSemanticMemory,
    S3ColdStorage,
    FourTierMemoryManager,
    EpisodeRecord,
    VectorRecord,
)

__all__ = [
    # Three-Tier
    'WorkingMemory', 'WorkingMemoryEntry',
    'EpisodicMemory', 'Episode',
    'SemanticMemory', 'Knowledge',
    'ProceduralMemory', 'Skill',
    'CompressionStrategy', 'CompressionConfig', 'CompressionReport',
    'RetrievalStrategy', 'RetrievalResult', 'MemoryRetriever',
    'MemoryGraph', 'GraphNode', 'GraphEdge',
    # Four-Tier
    'RedisWorkingMemory',
    'PostgreEpisodicMemory', 'EpisodeRecord',
    'QdrantSemanticMemory', 'VectorRecord',
    'S3ColdStorage',
    'FourTierMemoryManager',
]
