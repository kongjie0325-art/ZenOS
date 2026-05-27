"""AdaptiveRouter - Routes tasks to optimal strategies based on learned performance.

Uses multi-armed bandit (epsilon-greedy) to balance exploration of new strategies
vs exploitation of known good ones. Maintains per-strategy performance history
and auto-adjusts routing decisions.
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StrategyStats:
    """Performance statistics for a single strategy."""
    name: str
    total_attempts: int = 0
    successes: int = 0
    total_duration: float = 0.0
    total_tokens: int = 0
    last_used: float = 0.0
    recent_results: List[bool] = field(default_factory=list)  # last N results

    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.5  # unknown → neutral
        return self.successes / self.total_attempts

    @property
    def avg_duration(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.total_duration / self.total_attempts

    @property
    def recent_success_rate(self) -> float:
        if not self.recent_results:
            return self.success_rate
        return sum(1 for r in self.recent_results if r) / len(self.recent_results)

    @property
    def ucb_score(self) -> float:
        """Upper Confidence Bound score for exploration."""
        if self.total_attempts == 0:
            return float('inf')  # unexplored → high priority
        exploration = math.sqrt(2 * math.log(self.total_attempts + 1) / self.total_attempts)
        return self.success_rate + exploration

    def record(self, success: bool, duration: float = 0.0, tokens: int = 0) -> None:
        self.total_attempts += 1
        if success:
            self.successes += 1
        self.total_duration += duration
        self.total_tokens += tokens
        self.last_used = time.time()
        self.recent_results.append(success)
        if len(self.recent_results) > 20:
            self.recent_results = self.recent_results[-20:]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'attempts': self.total_attempts,
            'success_rate': round(self.success_rate, 3),
            'recent_success_rate': round(self.recent_success_rate, 3),
            'avg_duration': round(self.avg_duration, 3),
            'total_tokens': self.total_tokens,
        }


class AdaptiveRouter:
    """Routes tasks to strategies based on learned performance.

    Strategies:
    - direct: Simple tool call, no planning
    - chain: Chain of tool calls with reasoning
    - plan: Full task decomposition + planning loop
    - reflect: Full loop with self-reflection

    The router uses epsilon-greedy with UCB for exploration.
    """

    STRATEGIES = ["direct", "chain", "plan", "reflect"]

    def __init__(self, epsilon: float = 0.2, min_attempts: int = 3):
        self._epsilon = epsilon
        self._min_attempts = min_attempts
        self._stats: Dict[str, StrategyStats] = {
            name: StrategyStats(name=name) for name in self.STRATEGIES
        }
        self._task_history: List[Dict[str, Any]] = []

    def route(self, task: str, context: Optional[Dict] = None) -> str:
        """Select the best strategy for the given task."""
        context = context or {}

        # Heuristic pre-filtering based on task complexity
        complexity = self._estimate_complexity(task, context)

        if complexity < 0.3:
            # Simple tasks → always direct
            return "direct"
        elif complexity > 0.8:
            # Complex tasks → always plan or reflect
            candidates = ["plan", "reflect"]
        else:
            candidates = self.STRATEGIES

        # Epsilon-greedy selection
        if random.random() < self._epsilon:
            # Explore: pick random candidate
            choice = random.choice(candidates)
            logger.debug("Router: exploring '%s' (ε=%.2f)", choice, self._epsilon)
        else:
            # Exploit: pick best UCB score among candidates
            min_attempts_met = sum(
                1 for c in candidates if self._stats[c].total_attempts >= self._min_attempts
            )
            if min_attempts_met < len(candidates):
                # Not all explored → pick least-tried
                choice = min(candidates, key=lambda c: self._stats[c].total_attempts)
            else:
                # All explored → pick best recent success rate
                choice = max(candidates, key=lambda c: self._stats[c].recent_success_rate)
            logger.debug("Router: exploiting '%s'", choice)

        return choice

    def record_outcome(self, strategy: str, success: bool, duration: float = 0.0,
                       tokens: int = 0, task: str = "") -> None:
        """Record the outcome of using a strategy."""
        if strategy in self._stats:
            self._stats[strategy].record(success, duration, tokens)
        self._task_history.append({
            'strategy': strategy,
            'success': success,
            'duration': duration,
            'task': task[:100],
            'timestamp': time.time(),
        })
        # Trim history
        if len(self._task_history) > 1000:
            self._task_history = self._task_history[-1000:]

    def _estimate_complexity(self, task: str, context: Dict) -> float:
        """Estimate task complexity score (0-1)."""
        score = 0.0

        # Length heuristic
        words = len(task.split())
        if words > 50:
            score += 0.3
        elif words > 20:
            score += 0.15

        # Keyword indicators
        complex_keywords = ["analyze", "compare", "design", "implement", "optimize",
                            "refactor", "debug", "architecture", "system"]
        simple_keywords = ["find", "get", "show", "list", "count", "search", "read"]

        task_lower = task.lower()
        complex_count = sum(1 for kw in complex_keywords if kw in task_lower)
        simple_count = sum(1 for kw in simple_keywords if kw in task_lower)

        if complex_count > 0:
            score += min(0.4, complex_count * 0.15)
        if simple_count > 0:
            score -= min(0.2, simple_count * 0.1)

        # Context indicators
        if context.get("tools_needed", 0) > 3:
            score += 0.2
        if context.get("previous_failures", 0) > 0:
            score += 0.1

        return max(0.0, min(1.0, score))

    def get_stats(self) -> Dict[str, Any]:
        return {
            name: stats.to_dict() for name, stats in self._stats.items()
        }

    def recommend_strategy(self, task_type: str) -> str:
        """Recommend a strategy for a known task type."""
        task_type_lower = task_type.lower()
        if any(kw in task_type_lower for kw in ["search", "find", "get", "read"]):
            return "direct"
        elif any(kw in task_type_lower for kw in ["analyze", "compare", "summarize"]):
            return "chain"
        elif any(kw in task_type_lower for kw in ["build", "create", "implement", "design"]):
            return "plan"
        elif any(kw in task_type_lower for kw in ["debug", "fix", "optimize", "refactor"]):
            return "reflect"
        return max(self._stats, key=lambda s: self._stats[s].success_rate)
