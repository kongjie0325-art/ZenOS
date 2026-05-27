from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable

from ..storage.memory_store import MemoryEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scored item (generic)
# ---------------------------------------------------------------------------

@dataclass
class RankedItem:
    """A memory entry with its ranking information.

    Attributes:
        entry: The ranked memory entry.
        score: Final relevance score after re-ranking.
        original_rank: Position in the pre-re-ranking list.
        metadata: Additional ranking metadata.
    """

    entry: MemoryEntry
    score: float = 0.0
    original_rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Score normalisation utilities
# ---------------------------------------------------------------------------

class ScoreNormalizer:
    """Collection of static methods for normalising score lists."""

    @staticmethod
    def min_max(scores: list[float]) -> list[float]:
        """Scale scores to ``[0, 1]`` using min-max normalisation.

        Args:
            scores: Raw scores.

        Returns:
            Normalised scores.
        """
        if not scores:
            return []
        lo, hi = min(scores), max(scores)
        if hi == lo:
            return [0.5] * len(scores)
        return [(s - lo) / (hi - lo) for s in scores]

    @staticmethod
    def z_score(scores: list[float]) -> list[float]:
        """Standardise scores to zero mean and unit variance.

        Args:
            scores: Raw scores.

        Returns:
            Z-score normalised scores.
        """
        if not scores:
            return []
        n = len(scores)
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        std = math.sqrt(variance)
        if std == 0:
            return [0.0] * len(scores)
        return [(s - mean) / std for s in scores]

    @staticmethod
    def softmax(scores: list[float], *, temperature: float = 1.0) -> list[float]:
        """Apply the softmax function for probabilistic normalisation.

        Args:
            scores: Raw scores.
            temperature: Temperature parameter (higher ⇒ softer distribution).

        Returns:
            Probability distribution over scores.
        """
        if not scores:
            return []
        max_s = max(scores)
        exps = [math.exp((s - max_s) / temperature) for s in scores]
        total = sum(exps)
        return [e / total for e in exps]

    @staticmethod
    def rank_normalise(scores: list[float]) -> list[float]:
        """Convert scores to ``1 / (rank + 1)`` based on descending order.

        Args:
            scores: Raw scores.

        Returns:
            Rank-based normalised scores.
        """
        if not scores:
            return []
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        result = [0.0] * len(scores)
        for rank, idx in enumerate(ranked_indices):
            result[idx] = 1.0 / (rank + 1)
        return result


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion (RRF)
# ---------------------------------------------------------------------------

class ReciprocalRankFusion:
    """Fuse multiple ranked lists using Reciprocal Rank Fusion.

    Given *N* ranked lists, each item receives a fused score::

        score(d) = Σᵢ wᵢ · 1 / (k + rankᵢ(d))

    where ``k`` is a smoothing constant (default 60) and ``wᵢ`` is the
    weight for list *i*.

    Args:
        k: RRF constant that controls the influence of low-ranked items.
        weights: Optional per-list weights (uniform when ``None``).
    """

    def __init__(self, k: int = 60, weights: list[float] | None = None) -> None:
        self._k = k
        self._weights = weights

    def fuse(self, ranked_lists: list[list[int]]) -> dict[int, float]:
        """Fuse multiple ranked lists into a single score per item.

        Args:
            ranked_lists: Each inner list contains item indices sorted by
                relevance (best-first).  Items are identified by their
                integer index.

        Returns:
            Mapping of item index → fused score.
        """
        if not ranked_lists:
            return {}

        n_lists = len(ranked_lists)
        weights = self._weights or [1.0 / n_lists] * n_lists
        if len(weights) != n_lists:
            raise ValueError(
                f"Number of weights ({len(weights)}) must match number of lists ({n_lists})"
            )

        fused: dict[int, float] = {}
        for lst, weight in zip(ranked_lists, weights):
            for rank, item_idx in enumerate(lst):
                fused[item_idx] = fused.get(item_idx, 0.0) + weight * (
                    1.0 / (self._k + rank + 1)
                )
        return fused

    @staticmethod
    def from_score_lists(
        score_lists: list[list[float]],
        k: int = 60,
        weights: list[float] | None = None,
    ) -> list[float]:
        """Convenience: build ranked lists from raw scores, then fuse.

        Args:
            score_lists: One list of raw scores per ranking source.
            k: RRF constant.
            weights: Optional per-source weights.

        Returns:
            Fused scores aligned to the original item order.
        """
        ranked_lists = [
            sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            for scores in score_lists
        ]
        rrf = ReciprocalRankFusion(k=k, weights=weights)
        fused = rrf.fuse(ranked_lists)
        n = max((max(d.keys()) + 1 for d in [fused] if fused), default=0)
        return [fused.get(i, 0.0) for i in range(n)]


# ---------------------------------------------------------------------------
# Re-ranking strategies
# ---------------------------------------------------------------------------

class ReRanker:
    """Apply post-hoc re-ranking to a list of ``RankedItem`` objects.

    Supports several strategies that can be composed::

        reranker = ReRanker()
        results = reranker.rerank(
            items,
            strategies=[normalize, diversify, boost_recent],
        )

    Args:
        normaliser: Score normalisation method to apply before re-ranking.
    """

    def __init__(
        self,
        normaliser: Callable[[list[float]], list[float]] | None = None,
    ) -> None:
        self._normaliser = normaliser or ScoreNormalizer.min_max

    # -- public API --------------------------------------------------------

    def rerank(
        self,
        items: list[RankedItem],
        *,
        strategies: list[Callable[[list[RankedItem]], list[RankedItem]]] | None = None,
        top_k: int | None = None,
    ) -> list[RankedItem]:
        """Re-rank *items* using the given pipeline of strategies.

        Args:
            items: Pre-ranked items to re-order.
            strategies: Ordered list of re-ranking callables.  When
                ``None``, a default pipeline (normalise → sort) is used.
            top_k: If set, return only the top *k* results.

        Returns:
            Re-ranked list of items.
        """
        if not items:
            return []

        if strategies is None:
            strategies = [self._strategy_normalise, self._strategy_sort]

        current = list(items)
        for strategy in strategies:
            current = strategy(current)

        if top_k is not None:
            current = current[:top_k]
        return current

    # -- built-in strategies -----------------------------------------------

    @staticmethod
    def _strategy_normalise(items: list[RankedItem]) -> list[RankedItem]:
        scores = [i.score for i in items]
        normalised = ScoreNormalizer.min_max(scores)
        for item, ns in zip(items, normalised):
            item.score = ns
        return items

    @staticmethod
    def _strategy_sort(items: list[RankedItem]) -> list[RankedItem]:
        items.sort(key=lambda i: i.score, reverse=True)
        return items

    @staticmethod
    def strategy_diversify(
        items: list[RankedItem],
        *,
        similarity_threshold: float = 0.85,
        max_per_cluster: int = 1,
    ) -> list[RankedItem]:
        """MMR-style diversification: penalise items too similar to those already selected.

        Uses a simple Jaccard similarity over tokenised content.

        Args:
            items: Items to diversify.
            similarity_threshold: Above this, items are considered duplicates.
            max_per_cluster: Maximum items per similarity cluster.

        Returns:
            Diversified item list.
        """
        if not items:
            return []

        selected: list[RankedItem] = []
        remaining = list(items)

        while remaining:
            best = remaining[0]
            best_idx = 0

            for idx, candidate in enumerate(remaining):
                if candidate.score > best.score:
                    best = candidate
                    best_idx = idx

            selected.append(best)
            remaining.pop(best_idx)

            # Filter out near-duplicates
            new_remaining: list[RankedItem] = []
            for r in remaining:
                sim = ReRanker._jaccard(
                    best.entry.content,
                    r.entry.content,
                )
                if sim < similarity_threshold:
                    new_remaining.append(r)
            remaining = new_remaining

        return selected

    @staticmethod
    def strategy_boost_recent(
        items: list[RankedItem],
        *,
        half_life_seconds: float = 86400.0 * 7,
    ) -> list[RankedItem]:
        """Boost scores of recently-updated items using exponential decay.

        Args:
            items: Items to boost.
            half_life_seconds: Half-life for the temporal boost.

        Returns:
            Re-scored items.
        """
        import time as _time

        decay = math.log(2) / half_life_seconds
        now = _time.time()

        for item in items:
            age = max(0.0, now - item.entry.updated_at)
            boost = math.exp(-decay * age)
            item.score = item.score * (1.0 + boost)
            item.metadata["temporal_boost"] = boost

        items.sort(key=lambda i: i.score, reverse=True)
        return items

    @staticmethod
    def strategy_boost_importance(
        items: list[RankedItem],
        *,
        factor: float = 0.3,
    ) -> list[RankedItem]:
        """Add a fraction of the entry's ``importance`` field to its score.

        Args:
            items: Items to boost.
            factor: Scaling factor for the importance bonus.

        Returns:
            Re-scored items.
        """
        for item in items:
            bonus = item.entry.importance * factor
            item.score += bonus
            item.metadata["importance_bonus"] = bonus
        items.sort(key=lambda i: i.score, reverse=True)
        return items

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _jaccard(a: str, b: str) -> float:
        tokens_a = set(a.lower().split())
        tokens_b = set(b.lower().split())
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Convenience: build a default re-ranking pipeline
# ---------------------------------------------------------------------------

def default_reranker() -> ReRanker:
    """Return a ``ReRanker`` with min-max normalisation."""
    return ReRanker(normaliser=ScoreNormalizer.min_max)


def full_pipeline(
    items: list[RankedItem],
    *,
    limit: int = 10,
) -> list[RankedItem]:
    """Apply a complete re-ranking pipeline: normalise → boost recent → diversify → top-k.

    Args:
        items: Initial ranked items.
        limit: Maximum results to return.

    Returns:
        Final re-ranked items.
    """
    reranker = default_reranker()
    return reranker.rerank(
        items,
        strategies=[
            ReRanker._strategy_normalise,
            ReRanker._strategy_sort,
            ReRanker.strategy_boost_recent,
            ReRanker.strategy_boost_importance,
            ReRanker._strategy_sort,
            ReRanker.strategy_diversify,
            ReRanker._strategy_sort,
        ],
        top_k=limit,
    )
