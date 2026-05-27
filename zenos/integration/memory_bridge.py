"""MemoryBridge - Connects Agent to the three-tier memory system.

Features:
- Auto-compression when memory exceeds threshold
- Cross-session persistence (save/load to disk)
- Memory decay (reduce importance of old memories)
- Event-driven: publishes MEMORY_* events
- Memory graph: tracks relationships between memories
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class MemoryBridge:
    """Bridges Agent execution with the hierarchical memory system."""

    def __init__(
        self,
        working_memory: Any = None,
        episodic_memory: Any = None,
        semantic_memory: Any = None,
        compressor: Any = None,
        retriever: Any = None,
        event_bus: Any = None,
        persist_dir: str = "/tmp/zenos/memory",
        compression_threshold: float = 0.8,
        decay_rate: float = 0.01,
    ):
        self.working = working_memory
        self.episodic = episodic_memory
        self.semantic = semantic_memory
        self.compressor = compressor
        self.retriever = retriever
        self.event_bus = event_bus
        self.persist_dir = persist_dir
        self.compression_threshold = compression_threshold
        self.decay_rate = decay_rate
        self._access_count = 0
        self._last_compression = time.time()

    # ── Event helpers ──────────────────────────────────────────────

    async def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        if self.event_bus is None:
            return
        try:
            from zenos.core.events import Event, EventType
            try:
                et = EventType(event_type)
            except ValueError:
                return
            await self.event_bus.publish(Event(type=et, data=data, source="memory_bridge"))
        except Exception:
            pass

    # ── Cross-session persistence ──────────────────────────────────

    def save_session(self, session_id: str) -> bool:
        """Save all memory to disk for the given session."""
        try:
            dir_path = Path(self.persist_dir) / session_id
            dir_path.mkdir(parents=True, exist_ok=True)

            # Save episodic memory
            if self.episodic is not None:
                episodes = []
                try:
                    for ep in self.episodic.get_episodes():
                        episodes.append({
                            'id': ep.id,
                            'content': ep.content,
                            'timestamp': ep.timestamp.isoformat() if hasattr(ep.timestamp, 'isoformat') else str(ep.timestamp),
                            'importance': ep.importance,
                            'metadata': ep.metadata,
                        })
                except Exception:
                    pass
                (dir_path / "episodic.json").write_text(json.dumps(episodes, indent=2))

            # Save semantic memory
            if self.semantic is not None:
                knowledge = []
                try:
                    for k in self.semantic._store.values():
                        knowledge.append({
                            'id': k.id,
                            'content': k.content,
                            'timestamp': k.timestamp.isoformat() if hasattr(k.timestamp, 'isoformat') else str(k.timestamp),
                            'importance': k.importance,
                            'metadata': k.metadata,
                        })
                except Exception:
                    pass
                (dir_path / "semantic.json").write_text(json.dumps(knowledge, indent=2))

            logger.info("Saved session '%s' to %s", session_id, dir_path)
            return True
        except Exception as e:
            logger.error("Failed to save session: %s", e)
            return False

    def load_session(self, session_id: str) -> bool:
        """Load memory from disk for the given session."""
        try:
            dir_path = Path(self.persist_dir) / session_id
            if not dir_path.exists():
                logger.info("No saved session found for '%s'", session_id)
                return False

            # Load episodic memory
            ep_file = dir_path / "episodic.json"
            if ep_file.exists() and self.episodic is not None:
                from zenos.memory.episodic import Episode
                episodes = json.loads(ep_file.read_text())
                for ep_data in episodes:
                    try:
                        ep = Episode(
                            content=ep_data['content'],
                            importance=ep_data.get('importance', 0.5),
                            metadata=ep_data.get('metadata', {}),
                        )
                        self.episodic.add_episode(ep)
                    except Exception:
                        continue

            # Load semantic memory
            sem_file = dir_path / "semantic.json"
            if sem_file.exists() and self.semantic is not None:
                from zenos.memory.semantic import Knowledge
                items = json.loads(sem_file.read_text())
                for k_data in items:
                    try:
                        k = Knowledge(
                            content=k_data['content'],
                            importance=k_data.get('importance', 0.5),
                            metadata=k_data.get('metadata', {}),
                        )
                        self.semantic.add_knowledge(k)
                    except Exception:
                        continue

            logger.info("Loaded session '%s' from %s", session_id, dir_path)
            return True
        except Exception as e:
            logger.error("Failed to load session: %s", e)
            return False

    # ── Auto-compression ──────────────────────────────────────────

    def check_and_compress(self) -> Dict[str, Any]:
        """Check memory usage and compress if above threshold."""
        result = {'compressed': False, 'episodes_before': 0, 'episodes_after': 0}

        if self.episodic is None or self.compressor is None:
            return result

        try:
            episodes = self.episodic.get_episodes()
            result['episodes_before'] = len(episodes)

            # Check if compression needed
            if len(episodes) < 10:
                return result

            # Calculate usage ratio (assume soft limit of 1000 episodes)
            usage_ratio = len(episodes) / 1000.0
            if usage_ratio < self.compression_threshold:
                return result

            # Compress: keep top N by importance, summarize rest
            episodes.sort(key=lambda e: -e.importance)
            keep_n = min(100, int(len(episodes) * 0.3))  # keep top 30%
            to_keep = episodes[:keep_n]
            to_remove = episodes[keep_n:]

            # Remove low-importance episodes
            for ep in to_remove:
                try:
                    self.episodic.forget(ep.id)
                except Exception:
                    continue

            result['compressed'] = True
            result['episodes_after'] = len(to_keep)
            result['removed'] = len(to_remove)
            self._last_compression = time.time()

            logger.info("Compressed episodic memory: %d → %d episodes",
                        result['episodes_before'], result['episodes_after'])

            # Emit compression event
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._emit("memory.compress", result))
            except RuntimeError:
                pass

        except Exception as e:
            logger.error("Compression failed: %s", e)

        return result

    # ── Memory decay ───────────────────────────────────────────────

    def apply_decay(self) -> int:
        """Reduce importance of old memories. Returns count of decayed items."""
        if self.episodic is None:
            return 0

        decayed = 0
        try:
            now = time.time()
            for ep in self.episodic.get_episodes():
                try:
                    ts = ep.timestamp
                    if hasattr(ts, 'timestamp'):
                        ts = ts.timestamp()
                    age_hours = (now - float(ts)) / 3600.0
                    # Exponential decay: importance *= e^(-decay_rate * age)
                    import math
                    decay_factor = math.exp(-self.decay_rate * age_hours)
                    new_importance = ep.importance * decay_factor
                    if new_importance < 0.01:
                        new_importance = 0.01  # floor
                    if abs(new_importance - ep.importance) > 0.001:
                        ep.importance = new_importance
                        decayed += 1
                except Exception:
                    continue
        except Exception as e:
            logger.error("Decay failed: %s", e)

        if decayed > 0:
            logger.debug("Applied decay to %d memories", decayed)
        return decayed

    # ── Memory graph (relationship tracking) ──────────────────────

    def find_related(self, content: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Find memories related to the given content."""
        if self.retriever is None:
            return []
        try:
            from zenos.memory.retrieval import RetrievalStrategy
            results = self.retriever.retrieve(content, strategy=RetrievalStrategy.HYBRID, limit=limit)
            return [
                {'id': r.item_id, 'content': r.content, 'score': r.score, 'source': r.source}
                for r in results
            ]
        except Exception:
            return []

    def build_context(self, query: str, max_items: int = 10) -> str:
        """Build a context string from relevant memories for the agent."""
        parts = []

        # Get from episodic memory
        if self.episodic is not None:
            try:
                recent = self.episodic.get_episodes()
                if recent:
                    recent = sorted(recent, key=lambda e: getattr(e, 'timestamp', 0), reverse=True)
                    recent = recent[:max_items // 2]
                    parts.append("## Recent Episodes:")
                    for ep in recent:
                        parts.append(f"- [{ep.importance:.1f}] {ep.content[:200]}")
            except Exception:
                pass

        # Get from semantic memory
        if self.semantic is not None:
            try:
                results = self.semantic.search(query_text=query, top_k=max_items // 2)
                if results:
                    parts.append("\n## Relevant Knowledge:")
                    for k in results:
                        parts.append(f"- [{k.importance:.1f}] {k.content[:200]}")
            except Exception:
                pass

        return "\n".join(parts)

    # ── Lifecycle ──────────────────────────────────────────────────

    async def on_agent_start(self, goal: str) -> None:
        """Called when agent starts. Loads previous context."""
        related = self.find_related(goal, limit=3)
        if related:
            logger.info("Found %d related memories for goal: %s", len(related), goal[:80])
        await self._emit("memory.read", {"goal": goal, "related_count": len(related)})

    async def on_agent_complete(self, goal: str, iterations: int) -> None:
        """Called when agent completes. Triggers compression and persistence."""
        # Check compression
        self.check_and_compress()
        # Apply decay
        self.apply_decay()
        await self._emit("memory.write", {"goal": goal, "iterations": iterations})

    def get_stats(self) -> Dict[str, Any]:
        stats = {}
        if self.episodic is not None:
            try:
                stats['episodic_count'] = len(self.episodic)
            except Exception:
                pass
        if self.semantic is not None:
            try:
                stats['semantic_count'] = len(self.semantic)
            except Exception:
                pass
        if self.working is not None:
            try:
                stats['working'] = self.working.get_stats()
            except Exception:
                pass
        stats['last_compression'] = self._last_compression
        return stats
