from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..storage.memory_store import MemoryEntry, MemoryStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scored result
# ---------------------------------------------------------------------------

@dataclass
class ScoredResult:
    """A memory entry paired with its relevance score and source info.

    Attributes:
        entry: The retrieved memory entry.
        score: Final fused relevance score.
        source: Which sub-search produced this result
        (``"keyword"``, ``"vector"``, ``"temporal"``).
        component_scores: Breakdown of individual scores.
    """

    entry: MemoryEntry
    score: float = 0.0
    source: str = ""
    component_scores: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Embedding protocol (dependency-injected)
# ---------------------------------------------------------------------------

class EmbeddingProvider(Protocol):
    """Anything that can turn text into a vector."""

    async def embed(self, text: str) -> list[float]: ...


# ---------------------------------------------------------------------------
# BM25 keyword scorer (pure-Python, no external deps)
# ---------------------------------------------------------------------------

class BM25KeywordScorer:
    """Lightweight BM25 implementation for in-process keyword scoring.

    This scorer tokenises all entries at construction time and can
    score arbitrary query strings against them.  It is suitable for
    small-to-medium collections (tens of thousands of entries).

    Args:
        k1: BM25 ``k1`` parameter (term-frequency saturation).
        b: BM25 ``b`` parameter (document-length normalisation).
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._entries: list[MemoryEntry] = []
        self._token_freqs: list[dict[str, int]] = []
        self._avg_dl: float = 0.0
        self._idf: dict[str, float] = {}

    # -- indexing ----------------------------------------------------------

    def index(self, entries: list[MemoryEntry]) -> None:
        """Build the BM25 index from *entries*."""
        self._entries = entries
        self._token_freqs = [self._tokenise(e.content) for e in entries]
        total_dl = sum(len(tf) for tf in self._token_freqs)
        n = len(entries)
        self._avg_dl = total_dl / n if n else 0.0

        # Document frequency
        df: dict[str, int] = {}
        for tf in self._token_freqs:
            for term in tf:
                df[term] = df.get(term, 0) + 1

        # IDF (Roberson/Spark variant)
        self._idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }
        logger.debug("BM25 indexed %d documents (avg_dl=%.1f)", n, self._avg_dl)

    # -- scoring -----------------------------------------------------------

    def score(self, query: str) -> list[float]:
        """Return BM25 scores for *query* against the indexed entries."""
        q_terms = self._tokenise(query)
        if not q_terms:
            return [0.0] * len(self._entries)

        scores: list[float] = []
        for tf in self._token_freqs:
            dl = len(tf)
            score = 0.0
            norm = 1.0 - self._b + self._b * (dl / self._avg_dl if self._avg_dl else 1.0)
            for term in q_terms:
                if term not in self._idf:
                    continue
                freq = tf.get(term, 0)
                score += self._idf[term] * (freq * (self._k1 + 1)) / (freq + self._k1 * norm)
            scores.append(score)
        return scores

    # -- internal ----------------------------------------------------------

    @staticmethod
    def _tokenise(text: str) -> dict[str, int]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        freq: dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        return freq


# ---------------------------------------------------------------------------
# Temporal decay scorer
# ---------------------------------------------------------------------------

class TemporalScorer:
    """Scores entries based on recency using exponential decay.

    Args:
        half_life: Number of seconds after which the score decays to 0.5.
    """

    def __init__(self, half_life: float = 86400.0 * 30) -> None:
        self._decay = math.log(2) / half_life

    def score(self, entries: list[MemoryEntry]) -> list[float]:
        now = time.time()
        return [math.exp(-self._decay * max(0.0, now - e.updated_at)) for e in entries]


# ---------------------------------------------------------------------------
# Hybrid search
# ---------------------------------------------------------------------------

@dataclass
class HybridSearchConfig:
    """Weights and parameters controlling the hybrid search fusion.

    Attributes:
        keyword_weight: Relative weight for BM25 scores.
        vector_weight: Relative weight for vector similarity scores.
        temporal_weight: Relative weight for recency scores.
        rrf_k: Constant used in Reciprocal Rank Fusion.
        half_life_seconds: Temporal decay half-life.
        min_combined_score: Minimum fused score to include in results.
    """

    keyword_weight: float = 0.4
    vector_weight: float = 0.4
    temporal_weight: float = 0.2
    rrf_k: int = 60
    half_life_seconds: float = 86400.0 * 30
    min_combined_score: float = 0.01


class HybridSearch:
    """Combines keyword (BM25), vector similarity, and temporal signals.

    The search pipeline is:

    1. Fetch candidate entries from the store (full scan or vector query).
    2. Score each candidate with BM25, vector cosine similarity, and
       temporal decay.
    3. Normalise each sub-score to ``[0, 1]`` using min-max scaling.
    4. Fuse via a weighted sum **and** Reciprocal Rank Fusion (RRF),
       then average the two fused scores for the final ranking.

    Args:
        store: A ``MemoryStore`` used to fetch candidates.
        config: Fusion weights and parameters.
        embedding_provider: Optional provider for query embeddings.
    """

    def __init__(
        self,
        store: MemoryStore,
        config: HybridSearchConfig | None = None,
        *,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._store = store
        self._config = config or HybridSearchConfig()
        self._embedding_provider = embedding_provider

    # -- public API --------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        candidate_multiplier: int = 5,
    ) -> list[ScoredResult]:
        """Run the full hybrid search pipeline.

        Args:
            query: User query text.
            limit: Maximum number of results to return.
            candidate_multiplier: Fetch ``limit * multiplier`` candidates
                so that the re-ranking has a larger pool to work with.

        Returns:
            Ranked list of ``ScoredResult`` objects, best-first.
        """
        candidate_limit = limit * candidate_multiplier

        # 1. Gather candidates from the store (keyword-based)
        keyword_results = await self._store.search(query, limit=candidate_limit)

        # 2. Optionally gather vector candidates
        vector_results: list[MemoryEntry] = []
        query_vector: list[float] | None = None
        if self._embedding_provider is not None:
            try:
                query_vector = await self._embedding_provider.embed(query)
                vector_results = await self._store.search(
                    query, limit=candidate_multiplier
                )
            except Exception:
                logger.warning("Embedding provider failed – skipping vector search", exc_info=True)

        # Deduplicate by ID
        seen: dict[str, MemoryEntry] = {}
        for e in keyword_results:
            seen[e.id] = e
        for e in vector_results:
            if e.id not in seen:
                seen[e.id] = e
        candidates = list(seen.values())

        if not candidates:
            return []

        # 3. Score each sub-signal
        bm25 = BM25KeywordScorer()
        bm25.index(candidates)
        keyword_scores = bm25.score(query)

        temporal = TemporalScorer(half_life=self._config.half_life_seconds)
        temporal_scores = temporal.score(candidates)

        vector_scores = self._compute_vector_scores(candidates, query_vector)

        # 4. Normalise
        keyword_scores = self._min_max_normalise(keyword_scores)
        vector_scores = self._min_max_normalise(vector_scores)
        temporal_scores = self._min_max_normalise(temporal_scores)

        # 5. Weighted-sum fusion
        ws_scores: list[float] = []
        for i in range(len(candidates)):
            ws = (
                self._config.keyword_weight * keyword_scores[i]
                + self._config.vector_weight * vector_scores[i]
                + self._config.temporal_weight * temporal_scores[i]
            )
            ws_scores.append(ws)

        # 6. RRF fusion
        rrf_scores = self._reciprocal_rank_fusion(keyword_scores, vector_scores, temporal_scores)

        # 7. Average the two fusion strategies
        results: list[ScoredResult] = []
        for i, entry in enumerate(candidates):
            combined = 0.5 * ws_scores[i] + 0.5 * rrf_scores[i]
            if combined < self._config.min_combined_score:
                continue
            results.append(
                ScoredResult(
                    entry=entry,
                    score=combined,
                    source="hybrid",
                    component_scores={
                        "keyword": keyword_scores[i],
                        "vector": vector_scores[i],
                        "temporal": temporal_scores[i],
                        "weighted_sum": ws_scores[i],
                        "rrf": rrf_scores[i],
                    },
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    # -- internal helpers --------------------------------------------------

    def _compute_vector_scores(
        self,
        candidates: list[MemoryEntry],
        query_vector: list[float] | None,
    ) -> list[float]:
        if query_vector is None:
            return [0.0] * len(candidates)
        scores: list[float] = []
        for entry in candidates:
            if entry.embedding is not None:
                scores.append(self._cosine_similarity(query_vector, entry.embedding))
            else:
                scores.append(0.0)
        return scores

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _min_max_normalise(values: list[float]) -> list[float]:
        if not values:
            return []
        lo = min(values)
        hi = max(values)
        if hi == lo:
            return [0.5] * len(values)
        return [(v - lo) / (hi - lo) for v in values]

    def _reciprocal_rank_fusion(
        self,
        keyword_scores: list[float],
        vector_scores: list[float],
        temporal_scores: list[float],
    ) -> list[float]:
        """Apply RRF across three ranked lists and return a fused score per entry."""
        k = self._config.rrf_k
        rrf: list[float] = [0.0] * len(keyword_scores)

        for scores, weight in [
            (keyword_scores, self._config.keyword_weight),
            (vector_scores, self._config.vector_weight),
            (temporal_scores, self._config.temporal_weight),
        ]:
            ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            for rank, idx in enumerate(ranked):
                rrf[idx] += weight * (1.0 / (k + rank + 1))

        # Normalise to [0, 1]
        return self._min_max_normalise(rrf)
