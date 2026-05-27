"""MemoryGraph - Knowledge graph built from SemanticMemory items.

Builds a graph of related memories, supports traversal for context expansion,
community detection for clustering, and pruning for maintenance.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GraphNode:
    """A node in the memory graph (represents a Knowledge item)."""
    id: str
    content: str
    importance: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: Set[str] = field(default_factory=set)


@dataclass
class GraphEdge:
    """An edge in the memory graph (represents a relationship)."""
    source_id: str
    target_id: str
    relation: str = "related"  # related | causal | temporal | semantic
    weight: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)


class MemoryGraph:
    """Knowledge graph for semantic memory with traversal and clustering."""

    def __init__(self):
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []
        self._adjacency: Dict[str, List[Tuple[str, float]]] = defaultdict(list)  # node_id → [(neighbor_id, weight)]

    # ── Node/edge management ───────────────────────────────────────

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node

    def add_edge(self, source_id: str, target_id: str, relation: str = "related",
                 weight: float = 0.5, **metadata) -> bool:
        if source_id not in self._nodes or target_id not in self._nodes:
            return False
        edge = GraphEdge(source_id, target_id, relation, weight, metadata)
        self._edges.append(edge)
        self._adjacency[source_id].append((target_id, weight))
        self._adjacency[target_id].append((source_id, weight))  # undirected
        return True

    def remove_node(self, node_id: str) -> bool:
        if node_id not in self._nodes:
            return False
        del self._nodes[node_id]
        self._edges = [e for e in self._edges if e.source_id != node_id and e.target_id != node_id]
        self._adjacency.pop(node_id, None)
        for nid in self._adjacency:
            self._adjacency[nid] = [(t, w) for t, w in self._adjacency[nid] if t != node_id]
        return True

    def prune_weak_edges(self, threshold: float = 0.1) -> int:
        """Remove edges with weight below threshold."""
        before = len(self._edges)
        self._edges = [e for e in self._edges if e.weight >= threshold]
        # Rebuild adjacency
        self._adjacency.clear()
        for e in self._edges:
            self._adjacency[e.source_id].append((e.target_id, e.weight))
            self._adjacency[e.target_id].append((e.source_id, e.weight))
        removed = before - len(self._edges)
        if removed > 0:
            logger.debug("Pruned %d weak edges (threshold=%.2f)", removed, threshold)
        return removed

    # ── Graph traversal ────────────────────────────────────────────

    def find_related(self, node_id: str, depth: int = 2, min_weight: float = 0.1) -> List[Dict[str, Any]]:
        """BFS traversal to find related nodes up to given depth."""
        if node_id not in self._nodes:
            return []

        visited: Set[str] = {node_id}
        current_level = {node_id}
        results = []

        for d in range(depth):
            next_level: Set[str] = set()
            for nid in current_level:
                for neighbor_id, weight in self._adjacency.get(nid, []):
                    if neighbor_id not in visited and weight >= min_weight:
                        visited.add(neighbor_id)
                        next_level.add(neighbor_id)
                        node = self._nodes.get(neighbor_id)
                        if node:
                            results.append({
                                'id': node.id,
                                'content': node.content[:200],
                                'importance': node.importance,
                                'depth': d + 1,
                                'weight': weight,
                            })
            current_level = next_level
            if not current_level:
                break

        results.sort(key=lambda r: (-r['weight'], r['depth']))
        return results

    def shortest_path(self, source_id: str, target_id: str) -> Optional[List[str]]:
        """Find shortest path between two nodes using BFS."""
        if source_id not in self._nodes or target_id not in self._nodes:
            return None

        from collections import deque
        queue = deque([(source_id, [source_id])])
        visited = {source_id}

        while queue:
            current, path = queue.popleft()
            if current == target_id:
                return path
            for neighbor_id, _ in self._adjacency.get(current, []):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, path + [neighbor_id]))
        return None

    # ── Community detection (simple label propagation) ─────────────

    def get_communities(self, iterations: int = 10) -> Dict[str, int]:
        """Detect communities using label propagation. Returns node_id → community_id."""
        if not self._nodes:
            return {}

        # Initialize: each node is its own community
        labels: Dict[str, int] = {nid: i for i, nid in enumerate(self._nodes)}

        for _ in range(iterations):
            updated = False
            for node_id in self._nodes:
                neighbor_labels: Dict[int, float] = defaultdict(float)
                for neighbor_id, weight in self._adjacency.get(node_id, []):
                    neighbor_labels[labels[neighbor_id]] += weight

                if neighbor_labels:
                    best_label = max(neighbor_labels, key=lambda l: neighbor_labels[l])
                    if best_label != labels[node_id]:
                        labels[node_id] = best_label
                        updated = True

            if not updated:
                break

        return labels

    def get_community_summaries(self) -> List[Dict[str, Any]]:
        """Get summary of each community."""
        communities = self.get_communities()
        groups: Dict[int, List[str]] = defaultdict(list)
        for node_id, comm_id in communities.items():
            groups[comm_id].append(node_id)

        summaries = []
        for comm_id, node_ids in groups.items():
            nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]
            avg_importance = sum(n.importance for n in nodes) / len(nodes) if nodes else 0
            summaries.append({
                'community_id': comm_id,
                'size': len(node_ids),
                'avg_importance': round(avg_importance, 3),
                'members': [n.content[:100] for n in nodes[:5]],  # sample
            })

        summaries.sort(key=lambda s: -s['size'])
        return summaries

    # ── Build from SemanticMemory ──────────────────────────────────

    def build_from_semantic(self, semantic_memory: Any, similarity_threshold: float = 0.3) -> int:
        """Build graph from a SemanticMemory instance. Returns edge count."""
        try:
            items = list(semantic_memory._store.values())
        except Exception:
            return 0

        # Add nodes
        for item in items:
            node = GraphNode(
                id=item.id,
                content=item.content,
                importance=getattr(item, 'importance', 0.5),
                metadata=getattr(item, 'metadata', {}),
            )
            self.add_node(node)

        # Add edges based on content similarity (keyword overlap)
        edges_added = 0
        for i, item1 in enumerate(items):
            for item2 in items[i + 1:]:
                similarity = self._text_similarity(item1.content, item2.content)
                if similarity >= similarity_threshold:
                    self.add_edge(item1.id, item2.id, relation="semantic", weight=similarity)
                    edges_added += 1

        logger.info("Built memory graph: %d nodes, %d edges", len(self._nodes), edges_added)
        return edges_added

    @staticmethod
    def _text_similarity(text1: str, text2: str) -> float:
        """Simple Jaccard similarity on word sets."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union) if union else 0.0

    # ── Stats ──────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            'nodes': len(self._nodes),
            'edges': len(self._edges),
            'avg_degree': (
                sum(len(v) for v in self._adjacency.values()) / len(self._nodes)
                if self._nodes else 0
            ),
            'communities': len(set(self.get_communities().values())),
        }
