from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = ["RetrievalStrategy", "RetrievalResult", "MemoryRetriever"]


class RetrievalStrategy(Enum):
    """Available retrieval strategies.

    - ``keyword``: BM25-style keyword matching.
    - ``semantic``: Vector similarity search.
    - ``temporal``: Time-ordered retrieval from episodic memory.
    - ``hybrid``: Combined keyword + semantic with reciprocal-rank fusion.
    """

    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"
    HYBRID = "hybrid"


@dataclass
class RetrievalResult:
    """A single retrieval hit.

    Attributes:
        source: Which memory store the result came from
            (``working``, ``episodic``, ``semantic``).
        item_id: The id of the retrieved item.
        content: The textual content of the item.
        score: Relevance score (higher is more relevant).
        metadata: Additional metadata from the source item.
    """

    source: str
    item_id: str
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryRetriever:
    """Multi-strategy retriever that spans working, episodic, and semantic
    memory stores.

    Combines results from multiple sources using configurable strategies
    and reciprocal-rank fusion for hybrid search.
    """

    def __init__(
        self,
        working: WorkingMemory | None = None,
        episodic: EpisodicMemory | None = None,
        semantic: SemanticMemory | None = None,
    ) -> None:
        self._working = working
        self._episodic = episodic
        self._semantic = semantic

    def retrieve(
        self,
        query: str,
        strategy: RetrievalStrategy = RetrievalStrategy.KEYWORD,
        top_k: int = 10,
        query_vector: list[float] | None = None,
    ) -> list[RetrievalResult]:
        """Retrieve relevant memories using the specified strategy.

        Args:
            query: The search query string.
            strategy: Which retrieval strategy to use.
            top_k: Maximum number of results to return.
            query_vector: Required for ``SEMANTIC`` and ``HYBRID`` strategies.

        Returns:
            A list of :class:`RetrievalResult` sorted by score descending.
        """
        if strategy == RetrievalStrategy.KEYWORD:
            return self._keyword_search(query, top_k)
        if strategy == RetrievalStrategy.SEMANTIC:
            return self._semantic_search(query_vector, top_k)
        if strategy == RetrievalStrategy.TEMPORAL:
            return self._temporal_search(query, top_k)
        if strategy == RetrievalStrategy.HYBRID:
            return self.hybrid_search(query, query_vector, top_k)
        raise ValueError(f"Unknown retrieval strategy: {strategy}")

    def hybrid_search(
        self,
        query: str,
        query_vector: list[float] | None = None,
        top_k: int = 10,
        keyword_weight: float = 0.4,
        semantic_weight: float = 0.6,
    ) -> list[RetrievalResult]:
        """Perform hybrid search combining keyword and semantic results
        using reciprocal-rank fusion.

        Args:
            query: Text query for keyword search.
            query_vector: Embedding for semantic search.
            top_k: Maximum number of results.
            keyword_weight: Weight for keyword scores during fusion.
            semantic_weight: Weight for semantic scores during fusion.

        Returns:
            Fused and re-ranked results.
        """
        keyword_results = self._keyword_search(query, top_k * 2)
        semantic_results: list[RetrievalResult] = []
        if query_vector is not None:
            semantic_results = self._semantic_search(query_vector, top_k * 2)

        # Reciprocal-rank fusion
        k_constant = 60.0  # standard RRF constant
        scores: dict[str, RetrievalResult] = {}

        for rank, result in enumerate(keyword_results):
            key = f"{result.source}:{result.item_id}"
            rrf_score = keyword_weight * (1.0 / (k_constant + rank + 1))
            scores[key] = RetrievalResult(
                source=result.source,
                item_id=result.item_id,
                content=result.content,
                score=rrf_score,
                metadata=result.metadata,
            )

        for rank, result in enumerate(semantic_results):
            key = f"{result.source}:{result.item_id}"
            rrf_score = semantic_weight * (1.0 / (k_constant + rank + 1))
            if key in scores:
                existing = scores[key]
                existing.score += rrf_score
            else:
                scores[key] = RetrievalResult(
                    source=result.source,
                    item_id=result.item_id,
                    content=result.content,
                    score=rrf_score,
                    metadata=result.metadata,
                )

        fused = sorted(scores.values(), key=lambda r: -r.score)
        return fused[:top_k]

    def rerank(
        self,
        results: list[RetrievalResult],
        query: str,
        boost_recent: bool = True,
        boost_importance: bool = True,
    ) -> list[RetrievalResult]:
        """Re-rank retrieval results with optional recency and importance
        boosting.

        Args:
            results: The initial retrieval results.
            query: The original query (used for exact-match boosting).
            boost_recent: If True, boost scores for more recent items.
            boost_importance: If True, boost scores for higher-importance items.

        Returns:
            Re-ranked results.
        """
        query_lower = query.lower()
        for result in results:
            bonus = 0.0

            # Exact query match bonus
            if query_lower in result.content.lower():
                bonus += 0.1

            # Recency boost
            if boost_recent and "timestamp" in result.metadata:
                from datetime import datetime

                ts = result.metadata["timestamp"]
                if isinstance(ts, datetime):
                    age_days = (datetime.now() - ts).days
                    bonus += max(0.0, 0.05 * (1.0 / (1 + age_days)))

            # Importance boost
            if boost_importance and "importance" in result.metadata:
                bonus += result.metadata["importance"] * 0.1

            result.score += bonus

        results.sort(key=lambda r: -r.score)
        return results

    # ------------------------------------------------------------------
    # Internal search implementations
    # ------------------------------------------------------------------

    def _keyword_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """Keyword search across all memory stores."""
        results: list[RetrievalResult] = []
        q = query.lower()

        # Working memory
        if self._working is not None:
            for entry in self._working.get_by_priority(min_priority=0):
                content_str = str(entry.content)
                if q in content_str.lower():
                    score = entry.priority / 10.0 + (entry.access_count * 0.01)
                    results.append(
                        RetrievalResult(
                            source="working",
                            item_id=entry.id,
                            content=content_str,
                            score=score,
                            metadata={
                                "priority": entry.priority,
                                "access_count": entry.access_count,
                            },
                        )
                    )

        # Episodic memory
        if self._episodic is not None:
            for ep in self._episodic.search(query, limit=top_k):
                results.append(
                    RetrievalResult(
                        source="episodic",
                        item_id=ep.id,
                        content=ep.content,
                        score=ep.importance,
                        metadata={
                            "timestamp": ep.timestamp,
                            "importance": ep.importance,
                            **ep.metadata,
                        },
                    )
                )

        # Semantic memory (keyword fallback)
        if self._semantic is not None:
            for knowledge in self._semantic.search(query_text=query, top_k=top_k):
                results.append(
                    RetrievalResult(
                        source="semantic",
                        item_id=knowledge.id,
                        content=knowledge.content,
                        score=knowledge.importance,
                        metadata={
                            "timestamp": knowledge.timestamp,
                            "importance": knowledge.importance,
                            **knowledge.metadata,
                        },
                    )
                )

        results.sort(key=lambda r: -r.score)
        return results[:top_k]

    def _semantic_search(
        self, query_vector: list[float] | None, top_k: int
    ) -> list[RetrievalResult]:
        """Vector similarity search against semantic memory."""
        if query_vector is None or self._semantic is None:
            return []
        results: list[RetrievalResult] = []
        for knowledge in self._semantic.search(
            query_vector=query_vector, top_k=top_k
        ):
            results.append(
                RetrievalResult(
                    source="semantic",
                    item_id=knowledge.id,
                    content=knowledge.content,
                    score=knowledge.importance,
                    metadata={
                        "timestamp": knowledge.timestamp,
                        "importance": knowledge.importance,
                        **knowledge.metadata,
                    },
                )
            )
        return results

    def _temporal_search(self, date_query: str, top_k: int) -> list[RetrievalResult]:
        """Temporal search against episodic memory by date string."""
        if self._episodic is None:
            return []
        episodes = self._episodic.get_timeline(date_query)
        return [
            RetrievalResult(
                source="episodic",
                item_id=ep.id,
                content=ep.content,
                score=ep.importance,
                metadata={
                    "timestamp": ep.timestamp,
                    "importance": ep.importance,
                    **ep.metadata,
                },
            )
            for ep in episodes[:top_k]
        ]
